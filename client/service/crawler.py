### NDS Crawler
# Periodically fetch new group data from all NDS servers
# Single thread will be enough
import logging
import threading
import time


from structs.nds import FetchGroupResponse


def start_crawler(app):
	"""NDS crawler to periodically fetch group data from NDS servers"""
	logging.info("CRWL: Got signal to start crawler...")
	if not app.crawler:
		app.crawler = threading.Thread(
			target=crawler_thread,
			args=(app, app.nds_servers, app.networking, app.active_group),
			daemon=True,
		)
		app.crawler.start()
	else:
		logging.info("CRWL: Crawler already running.")


def crawler_thread(app, nds_servers, networking, group):
	logging.info("CRWL: Crawler starting.")
	try:
		while True:
			logging.info("CRWL: Crawling.")
			for nds_ip, nds in nds_servers.items():
				response: FetchGroupResponse = FetchGroupResponse.from_json(
					nds.get_groups()
				)
				if response.ok:
					networking.reload_all_groups(nds_ip, group, response.groups)

			# Wait for a bit before fetching again
			time.sleep(app.crawler_refresh_rate)
	except Exception as e:
		logging.error(f"EXC: CRWL: Crawler failed {e}")
	finally:
		logging.info("CRWL: Crawler killed.")
