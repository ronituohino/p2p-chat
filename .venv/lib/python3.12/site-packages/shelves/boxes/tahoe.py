#!/usr/bin/env python

import threading
import re

import requests

from shelves.boxes.box import Box

class TahoeBox(Box):
    """
    This is a box stored in Tahoe-LAFS. We must be careful about the CAP we return, they should
    be READ cap most of the time. And direct CAP to file, not to directory. We will use a cached
    list of CAP <-> filename association, cache being refreshed by an async job.
    """
    cache_locked = False
    cache = {}

    def __build_cache(self):
        """
        Let's build the cache associating read-only CAP to file hash
        """
        if self.cache_locked:
            # We're already updating the cache
            return

        self.cache_locked = True

        r = requests.get(self.base, params={'t': 'json'})
        try:
            r.raise_for_status()
        except Exception, e:
            self.cache_locked = False
            raise e

        # So we got a positive answer, let's extract children of the DIR-CAP
        children = r.json()[1]['children']

        for child in children:
            # We want only files
            if children[child][0] != u"filenode":
                continue
            # file metadata are stored in children[child][1]
            child_metadata = children[child][1]
            self.cache[child] = child_metadata["ro_uri"]

        # Now we need to remove docs who are in cache but not in the children
        for cached in cache:
            if cached not in children:
                chache.remove(cached)

        # Now we're done, unlock the cache and return
        self.cache_locked = False

        return

    def __init__(self, base_cap="", gateway_url=""):
        """
        We're going to initialize the box. If the base cap does not exist, we're going to create
        it.

        gateway_url points toward the Tahoe-LAFS gateway to be used by this Box, without the '/uri/' part
        base_cap is DIR CAP
        """
        super(Box, self).__init__()

        # We need to check if the CAP is a directory one AND if it's a writable one
        # That's wuite easy to do, since you just need to check it it starts by URI:DIR2:
        if re.match('^URI:DIR2:', base_cap) is None:
            # No match, so we fail
            raise Exception("Tahoe base_cap is incorrect")

        # We're now going to check if the directory exists.
        r = requests.head('/'.join([gateway_url, 'uri', base_cap]), params={'t': 'json'})
        try:
            r.raise_for_status()
        except requests.exceptions.ConnectionError, e:
            # We were not able to Connect, it means our address is borked
            raise e
        except requests.exceptions.HTTPError, e:
            # So, our requests most probably ended in 404. Let's be sure, and then
            # we would be able to create the CAP.
            if r.status_code != 404:
                raise e
            base_cap = ""

        # Let's create a directory into our tahoe-lafs
        if base_cap == "":
            r = requests.post('/'.join([gateway_url, 'uri'], params={'t': 'mkdir'}))
            r.raise_for_status()
            base_cap = r.content

        # The base_cap already exist or we created it
        self.gateway_url = gateway_url
        self.base = '/'.join([gateway_url, 'uri', base_cap])

        # We're going to build the cache.
        threading.Thread(target=self.__build_cache).start()

    def _list(self):
        """
        This method list content of the box. It's easy, you just have to return the cached keys.
        """
        return self.cache.keys()

    def _get(self, name):
        """
        We must return a file-descriptor like - in fact something which support .read method

        name is the hash we want the file for.
        """
        r = requests.get('/'.join([self.gateway_url, 'uri', self.cache[name]]))
        r.raise_for_status()
        return r.raw

    def _del(self, name):
        """
        We should unlink the file from our base directory. Also, we need to update the cache
        afterward.

        name is the hash we want to delete the file for.
        """
        if name not in self.cache:
            # The file does not exist
            raise IOError("FIle %s not found" % (name,))

        r = requests.delete('/'.join([self.base, name]), stream=True)
        r.raise_for_status()

        # Let's update the cache index
        threading.Thread(target=self.__build_cache).start()

    def _put(self, name, document):
        """
        We wanna add a document into our tahoe node.

        name is the hash of the document to add
        document is a file descriptor used to upload a document
        """
        # First, let's go back to the origin of the document
        document.seek(0)

        r = requests.put('/'.join([self.base, name]), files={name: document}, stream=True)
        r.raise_for_status()

        # Let's update the cache index
        threading.Thread(target=self.__build_cache).start()
