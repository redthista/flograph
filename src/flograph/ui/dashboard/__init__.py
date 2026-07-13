"""Dashboard pages ("app view"): renameable tabs below the canvas where the
flow's visual elements — Show Plot / Show Table / Show Plotly / Table Spec
outputs, KPI Cards, Slicers and Action Buttons — are laid out freely on an
infinite canvas for end users."""
from .dashboard_page import DashboardPage
from .page_bar import PageTabBar
from .tile_item import default_tile_port, default_tile_size, is_tile_able

__all__ = ["DashboardPage", "PageTabBar", "is_tile_able",
           "default_tile_port", "default_tile_size"]
