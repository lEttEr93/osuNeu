"""Tiny multi-label beatmap pattern model.

Input : per-hitobject feature sequence  (B, T, F)
Output: per-segment logits               (B, N, C)   N = T // SEG
        map-level logits (attention)     (B, C)

~0.2M parameters, pure conv -> trains on CPU in seconds for the synthetic set,
exports to ONNX for the C# side.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, ch: int, dilation: int, kernel: int = 3):
        super().__init__()
        pad = dilation * (kernel // 2)
        self.conv1 = nn.Conv1d(ch, ch, kernel, padding=pad, dilation=dilation)
        self.conv2 = nn.Conv1d(ch, ch, kernel, padding=pad, dilation=dilation)
        self.norm = nn.GroupNorm(4, ch)

    def forward(self, x):
        h = torch.relu(self.conv1(x))
        h = self.conv2(h)
        return torch.relu(self.norm(x + h))


class TinyPatternNet(nn.Module):
    def __init__(self, n_features: int, n_labels: int, ch: int = 64,
                 n_blocks: int = 3, seg: int = 32):
        super().__init__()
        self.seg = seg
        self.inp = nn.Conv1d(n_features, ch, 5, padding=2)
        self.blocks = nn.Sequential(
            *[ResidualBlock(ch, d) for d in (1, 2, 4)[:n_blocks]]
        )
        self.seg_head = nn.Sequential(
            nn.Linear(ch, ch), nn.GELU(), nn.Linear(ch, n_labels)
        )
        self.map_att = nn.Linear(ch, 1)
        self.map_head = nn.Linear(ch, n_labels)

    def forward(self, x: torch.Tensor):
        # x: (B, T, F) -> (B, C, T)
        h = torch.relu(self.inp(x.transpose(1, 2)))
        h = self.blocks(h)

        # pad T to a multiple of seg, then pool each segment.
        # NOTE: pad unconditionally -- a tracing-time `if pad:` would be folded
        # away and break dynamic shapes in the ONNX graph.
        b, c, t = h.shape
        pad = (self.seg - t % self.seg) % self.seg
        h = torch.nn.functional.pad(h, (0, pad))
        n = (t + pad) // self.seg
        seg = h.view(b, c, n, self.seg).mean(dim=3).transpose(1, 2)  # (B, N, C)

        seg_logits = self.seg_head(seg)                              # (B, N, L)

        # attention pooling over segments -> map-level logits (weak labels)
        w = torch.softmax(self.map_att(seg).squeeze(-1), dim=1)      # (B, N)
        pooled = (seg * w.unsqueeze(-1)).sum(dim=1)                  # (B, C)
        map_logits = self.map_head(pooled)                           # (B, L)
        return seg_logits, map_logits, w


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


if __name__ == "__main__":
    for ch, blocks in ((64, 3), (32, 2)):
        m = TinyPatternNet(18, 6, ch=ch, n_blocks=blocks)
        print(f"ch={ch} blocks={blocks}: {count_params(m):,} params "
              f"(~{count_params(m) * 4 / 1024 / 1024:.2f} MB fp32)")
