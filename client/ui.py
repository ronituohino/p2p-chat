from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Grid
from textual.screen import Screen
from textual.widgets import Footer, Static, Input, Tree, RichLog, Button
from textual.widget import Widget

banner = """
  ██████╗ ██████╗ ██████╗        ██████╗██╗  ██╗ █████╗ ████████╗
  ██╔══██╗╚════██╗██╔══██╗      ██╔════╝██║  ██║██╔══██╗╚══██╔══╝
  ██████╔╝ █████╔╝██████╔╝█████╗██║     ███████║███████║   ██║   
  ██╔═══╝ ██╔═══╝ ██╔═══╝ ╚════╝██║     ██╔══██║██╔══██║   ██║   
  ██║     ███████╗██║           ╚██████╗██║  ██║██║  ██║   ██║   
  ╚═╝     ╚══════╝╚═╝            ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
"""


class AddDiscoverySource(Screen):
	"""Screen with a dialog to add a new Discovery source"""

	def compose(self) -> ComposeResult:
		yield Grid(
			Input(id="input"),
			Button("Cancel", variant="error", id="cancel"),
			Button("Add", variant="primary", id="add"),
			id="dialog",
		)

	def on_button_pressed(self) -> None:
		self.app.pop_screen()


class Discovery(Static):
	BORDER_TITLE = "Discovery"

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


class Groups(Static):
	BORDER_TITLE = "Groups"

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree: Tree[str] = Tree("Dune")
			tree.root.expand()
			characters = tree.root.add("Characters")
			characters.add_leaf("Paul")
			characters.add_leaf("Jessica")
			characters.add_leaf("Chani")
			yield tree


class Chat(Widget):
	BORDER_TITLE = "Chat"

	def write(self, msg: str):
		self.query_one(RichLog).write(msg)

	def on_mount(self):
		self.write(banner)

	def on_input_submitted(self, event: Input.Submitted):
		event.input.clear()
		self.write(f"@me: {event.value}")

	def compose(self) -> ComposeResult:
		yield RichLog(wrap=True, auto_scroll=True)
		yield Input(classes="message-input")


class ChatApp(App):
	"""The main ui class"""

	CSS_PATH = "chatapp.tcss"
	BINDINGS = [("a", "add_discovery", "Add Discovery source")]

	def compose(self) -> ComposeResult:
		with Horizontal(classes="column"):
			with Vertical(id="left", classes="column"):
				yield Discovery()
				yield Groups()
			yield Chat()
		yield Footer()

	def action_add_discovery(self) -> None:
		"""An action to add a new Discovery source"""
		self.push_screen(AddDiscoverySource())


def run():
	app = ChatApp()
	app.run()


if __name__ == "__main__":
	run()
