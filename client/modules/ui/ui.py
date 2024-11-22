from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer

from modules.ui.Chat.main import Chat
from modules.ui.Networks.main import Networks
from modules.ui.Networks.add_discovery_source import AddDiscoverySource
from modules.ui.Networks.create_group import CreateGroup


# Structs for objects
class Group:
	def __init__(self, name) -> None:
		self.name = name


class Node:
	def __init__(self, name) -> None:
		self.name = name


class ChatApp(App):
	"""The main ui class"""

	DEFAULT_CSS = """
	Networks {
    width: 30%;
	}

	$border: round darkblue;
	"""

	BINDINGS = [
		("a", "add_discovery", "Add Discovery source"),
		("c", "create_group", "Create Group"),
	]

	def __init__(self, net) -> None:
		self.net = net
		self.chat = None
		self.networks = None
		super().__init__()

	def on_mount(self):
		chat = self.query_one("Chat")
		self.chat = chat
		networks = self.query_one("Networks")
		self.networks = networks
		self.net.register_ui(self)

	def compose(self) -> ComposeResult:
		with Horizontal():
			yield Networks()
			yield Chat()
		yield Footer()

	def action_add_discovery(self) -> None:
		"""An action to add a new Discovery source"""
		self.push_screen(AddDiscoverySource())

	def action_create_group(self) -> None:
		"""An action to create a new group"""
		self.push_screen(CreateGroup())
