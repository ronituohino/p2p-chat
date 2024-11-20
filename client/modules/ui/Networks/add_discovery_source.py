from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Input, Button


class AddDiscoverySource(Screen):
	"""Screen with a dialog to add a new Discovery source"""

	DEFAULT_CSS = """
	AddDiscoverySource {
    align: center middle;
    background: rgba(0,0,0, 0.75);
	}

	#dialog {
			grid-size: 2;
			grid-gutter: 1 2;
			grid-rows: 1fr 3;
			padding: 0 1;
			width: 60;
			height: 11;
			border: thick $background 80%;
			background: $surface;
	}

	Input {
			column-span: 2;
			height: 1fr;
			width: 1fr;
			content-align: center middle;
	}
	"""

	def compose(self) -> ComposeResult:
		yield Grid(
			Input(),
			Button("Cancel", variant="error"),
			Button("Add", variant="primary", id="add"),
			id="dialog",
		)

	async def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "add":
			nds_ip = self.query_one("Input").value
			groups = await self.app.net.add_discovery_source(nds_ip)
			self.app.networks.add_groups(nds_ip, groups)
		self.app.pop_screen()
