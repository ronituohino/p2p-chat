from textual.app import ComposeResult
from textual.widgets import Input, Static, RichLog
from structs.client import Group

banner = """
  ██████╗ ██████╗ ██████╗        ██████╗██╗  ██╗ █████╗ ████████╗
  ██╔══██╗╚════██╗██╔══██╗      ██╔════╝██║  ██║██╔══██╗╚══██╔══╝
  ██████╔╝ █████╔╝██████╔╝█████╗██║     ███████║███████║   ██║   
  ██╔═══╝ ██╔═══╝ ██╔═══╝ ╚════╝██║     ██╔══██║██╔══██║   ██║   
  ██║     ███████╗██║           ╚██████╗██║  ██║██║  ██║   ██║   
  ╚═╝     ╚══════╝╚═╝            ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
"""


class Chat(Static):
	BORDER_TITLE = "Chat"

	DEFAULT_CSS = """
	Chat {
    border: $border;
    background: blue;
    max-width: 70%;
	}

	RichLog {
		overflow-x: hidden; 
	}

	.message-input {
			dock: bottom;
			background: red;
	}
	"""

	def __init__(self):
		super().__init__()
		self.chat_log = None
		self.active_group: None | Group = None

	def set_active_group(self, group: Group):
		print("active group set")
		self.chat_log.clear()
		self.active_group = group

	def write(self, msg: str):
		self.chat_log.write(msg, width=66)

	def on_mount(self):
		self.chat_log = self.query_one(RichLog)
		self.write(banner)

	def on_input_submitted(self, event: Input.Submitted):
		event.input.clear()
		self.send_message(event.value, self.active_group.group_id)

	async def send_message(self, message, group_id):
		await self.app.net.send_message(message, group_id)
		self.write(f"@me: {message}")

	def compose(self) -> ComposeResult:
		yield RichLog(wrap=True, auto_scroll=True)
		yield Input(classes="message-input")
