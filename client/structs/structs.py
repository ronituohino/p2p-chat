from dataclasses import dataclass

"""
	Structs for commonly used objects.
	Make sure to add re-exports to __init__.py for new additions.
"""


@dataclass
class Group:
	"""
	A class used to represent a Group.

	Attributes
	----------
	name : str
		The name of the group. This field is mandatory.
	group_id : str
		The unique identifier of the group. This field is mandatory.
	leader_ip : str
		The IP address of the group leader. This field is mandatory.
	"""

	name: str
	group_id: str
	leader_ip: str


@dataclass
class Node:
	"""
	A class used to represent any Node (e.g. another client).

	Attributes
	----------
	name : str
		The name of the node. This field is mandatory.
	"""

	name: str


@dataclass
class NDSResponse:
	"""
	A class for transforming dict type data received from NDS.

	Attributes
	----------
	response : dict
	    The entire response dictionary from NDS.
	"""

	response: dict

	@property
	def success(self) -> bool:
		return self.response.get("success", False)

	@property
	def message(self) -> str:
		return self.response.get("message", "")

	@property
	def data(self) -> dict:
		return self.response.get("data", {})


class Response:
	"""
	A class for transforming dict type data received from NDS.

	Attributes
	----------
	response : dict
	    The entire response dictionary.
	"""

	response: dict

	@property
	def success(self) -> bool:
		return self.response.get("success", False)

	@property
	def message(self) -> str:
		return self.response.get("message", "")

	@property
	def data(self) -> dict:
		return self.response.get("data", {})