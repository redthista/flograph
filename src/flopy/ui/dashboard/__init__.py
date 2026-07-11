"""Dashboard pages ("app view"): renameable tabs below the canvas where the
flow's visual elements — Show Plot / Show Table / Show Plotly outputs and
Action Buttons — are laid out freely on an infinite canvas for end users."""
from .dashboard_page import DashboardPage
from .page_bar import PageTabBar
from .tile_item import TILE_ABLE_TYPES, default_tile_port, default_tile_size

__all__ = ["DashboardPage", "PageTabBar", "TILE_ABLE_TYPES",
           "default_tile_port", "default_tile_size"]
