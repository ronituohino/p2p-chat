from modules.ui import ui

import asyncio


# Stub Networking class, returns sample values
class Networking:
	def __init__(self) -> None:
		self.ui = None
		self.chat = None

	def register_ui(self, ui, chat):
		self.ui = ui
		self.chat = chat

	def add_discovery_source(self, ip):
		print(ip)

	def receive_message(self, msg):
		self.chat.write(msg)


# Stub Networking 'serve' command
async def repeater(net: Networking):
	asyncio.sleep(1)  # Wait for 1s just in case so that ui has time to init
	for i in range(100):
		await asyncio.sleep(1)
		net.receive_message(str(i))


async def main():
	net = Networking()
	app = ui.ChatApp(net=net)

	task1 = asyncio.create_task(app.run_async())
	task2 = asyncio.create_task(repeater(net=net))

	await task1
	await task2


if __name__ == "__main__":
	asyncio.run(main())
