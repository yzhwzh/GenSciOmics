"""Shared helpers for all skill modules."""

from __future__ import annotations

import io
import sys
import base64
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

_CONDA_SITE = Path('/data/yuanwuzhou/Software/Anaconda/envs/OmicVerse/lib/python3.10/site-packages')
if str(_CONDA_SITE) not in sys.path:
    sys.path.insert(0, str(_CONDA_SITE))


def _read_adata(real_path: str, backed: bool = False):
    import anndata
    return anndata.read_h5ad(real_path, backed='r' if backed else None)


def _img_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=300, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return data


def _ensure_log1p(adata):
    if 'log1p' not in adata.uns or 'base' not in adata.uns.get('log1p', {}):
        adata.uns['log1p'] = {'base': None}


def _gpu_init():
    import omicverse as ov
    try:
        ov.settings.cpu_gpu_mixed_init()
    except Exception:
        pass


def _init_publication_style():
    plt.rcParams.update({
        'figure.dpi': 150, 'savefig.dpi': 300,
        'font.size': 8, 'axes.labelsize': 9, 'axes.titlesize': 10,
        'xtick.labelsize': 7, 'ytick.labelsize': 7,
        'legend.fontsize': 7, 'legend.frameon': True,
        'pdf.fonttype': 42, 'ps.fonttype': 42,
        'font.family': 'sans-serif',
    })
    import seaborn as sns
    sns.set_theme(style='ticks', context='paper', palette='colorblind')
