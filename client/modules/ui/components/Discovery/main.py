from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class Discovery(Static):
	BORDER_TITLE = "Discovery"

	DEFAULT_CSS = """
	Discovery {
		border: $border;
		background: crimson;
		max-height: 30%;
	}
	"""

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			yield Static("Horizontally")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
