from dataclasses import dataclass

# Structs for objects


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
