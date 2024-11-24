#!/usr/bin/env python

import json

import requests

from shelves.boxes.box import Box

class RemoteBox(Box):
    """
    This box is, in fact, a remote shelf. We play with it by using REST API. But
    since it's a remote one we won't write in it. And so it's a readonly Box.
    """
    readonly = True
    def __init__(self, api_root=""):
        """
        We need a token_id to auth against the remote shelf. And then, to
        auth ourselves, that's somewhere we can save some time.
        """
        super(Box, self).__init__()

        self.api_root = api_root

    def _list(self):
        """
        List does not need auth, which is nice. We need to send a magic query with '*' in it.
        It will returns metadata, we just need to parse to get the media url.

        We must return a list of path.
        """
        # We will query for hash - it's a mandatory field, we sure it exist
        # and we're using the joker '*' because it will give us all the doc
        # stored there.
        data=json.dumps({'hash': '*'})
        headers={'Content-type': 'application/json'}

        results = []

        # Let's create the search.
        r = requests.put(self.api_root+'/search/', data=data, headers=headers)

        try:
            r.raise_for_status()
        except:
            return results

        # The search is in progress, we have to wait for it to be complete
        while r.json()['state'] != "done":
            r = requests.get(self.api_root+r.json()['uri']+'/')
            try:
                r.raise_for_status()
            except:
                return results

        # So now, we have an ended search query, with all the doc in them.
        for hit in r.json()['results']:
            # Each hit is a dict and have a 'doc_url' field, that's what we
            # to query at a later time.
            results.append(hit['doc_url'].split('/')[1])

        return results

    def _get(self, name):
        """
        Let's get a doc by its name, the name is a hash, we just need to assemble a URL
        """
        # We do have a document, we need to get the media url. ALso, streaming for the
        # win.
        r = requests.get('/'.join([self.api_root, 'media', name, '']), stream=True)

        # If we have an exception, it means document does not exist or
        # is unavailable
        try:
            r.raise_for_status()
        except:
            raise IOError("No such document in remote shelf")

        # requests .raw attrbute supports file like method (read, etc)
        return r.raw

    def _put(self, name, document):
        """
        We're not going to store a document in a remote-shelf, because we don't have
        the associated metadata.
        """
        raise IOError("Cannot put documents onto a remote shelf")

    def _del(self, name, document):
        """
        We're not going to delete document from a remote shelf, it might be used elsewhere.
        """
        raise IOError("Cannot delete document from a remote shelf")
