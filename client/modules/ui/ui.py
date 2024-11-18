from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer

from components.Chat.main import Chat
from components.Discovery.main import Discovery
from components.Discovery.add_discovery_source import AddDiscoverySource
from components.Groups.main import Groups


class ChatApp(App):
	"""The main ui class"""

	DEFAULT_CSS = """
	#left {
    width: 30%;
	}

	$border: round darkblue;
	"""

	BINDINGS = [("a", "add_discovery", "Add Discovery source")]

	def compose(self) -> ComposeResult:
		with Horizontal():
			with Vertical(id="left"):
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
