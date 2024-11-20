from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer

from modules.ui.Chat.main import Chat
from modules.ui.Networks.main import Networks
from modules.ui.Networks.add_discovery_source import AddDiscoverySource


class ChatApp(App):
	"""The main ui class"""

	DEFAULT_CSS = """
	Networks {
    width: 30%;
	}

	$border: round darkblue;
	"""

	BINDINGS = [("a", "add_discovery", "Add Discovery source")]

	def __init__(self, net) -> None:
		self.net = net
		super().__init__()

	def on_mount(self):
		self.net.register_ui(self, self.query_one("Chat"))

	def compose(self) -> ComposeResult:
		with Horizontal():
			yield Networks()
			yield Chat()
		yield Footer()

	def action_add_discovery(self) -> None:
		"""An action to add a new Discovery source"""
		self.push_screen(AddDiscoverySource())
