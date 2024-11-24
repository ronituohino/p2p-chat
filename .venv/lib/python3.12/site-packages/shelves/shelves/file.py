#!/usr/bin/env python

import os
from hashlib import sha1

from whoosh import index
from whoosh.query import Every
from whoosh.fields import ID
from whoosh.writing import AsyncWriter
from whoosh.qparser import QueryParser, MultifieldParser

from shelves.schemas.basic import BasicSchema
from shelves import boxes
from shelves.shelves.shelf import Shelf

class FileShelf(Shelf):
    """
    This class implement a shelf with a classic Whoosh index on filesystem and filed with FileBoxes
    """

    def __init__(self, index_dir, schema_class=BasicSchema, *args, **kwargs):
        """
        Initialize the shelf

        index_dir is where the Index will be stored
        schema_class is a class used as the schema of the shelf.
        """
        super(FileShelf, self).__init__(*args, **kwargs)

        # If the index_dir does not exists, let's create it
        if not os.path.exists(index_dir):
            os.mkdir(index_dir)

        # If there's already an index in index_dir, just open it
        if index.exists_in(index_dir):
            self.index = index.open_dir(index_dir)
        else:
            self.index = index.create_in(index_dir, schema_class())


    def __update_index(self, metadata):
        """
        This method is used inetrnally to update the index when needed
        """
        # Let's grab a writer to the index
        writer = AsyncWriter(self.index)

        # And now, let's crawl the metadata for unknown fields
        known_fields = self.index.schema.names()
        for k in metadata.keys():
            if k not in known_fields:
                writer.add_field(k, TEXT(stored=True))

        # We just need to add the document to the index now
        writer.update_document(**metadata)

        # Commit and close
        writer.commit()

    def add(self, document, metadata={}):
        """
        Add a document to the file index and to the boxes. Metadata is a dict.
        Each field not present in the current schema is added to it.
        """
        # We need at least one box on our shelf to store documents
        if len(self.boxes) == 0:
            raise IndexError

        # We generate a name for the document. The name must be the same for two similar files
        # So we need to hash it first
        shash = sha1()
        with open(document) as f:
            shash.update(f.read())
        name = unicode(shash.hexdigest())

        metadata['hash'] = name

        # Write everything into the index
        self.__update_index(metadata)

        # Let's check if the document exist in a FileBox
        exist = False
        for box in self.boxes:
            if box.has_key(unicode(name)):
                exist = True
                break

        # if it does not, add it to the first writable Box
        for box in self.boxes:
            if box.readable:
                box[0][unicode(name)] = open(document)
                break

        # We return the name of the newly created doc
        return name

    def delete(self, name, purge=True):
        """
        Delete a document by its name. name is actually a hash. If purge is true, file is also
        removed from the boxes.
        """
        # Grab a writer on the index
        writer = AsyncWriter(self.index)

        # Delete and commit ffom index
        writer.delete_by_term(u'hash', name)
        writer.commit()

        # Delete the document from the boxes if we want to purge them
        if not purge:
            return

        # We need to remove the doc is box is writable
        for box in self.boxes:
            if box.haskey(name) and not box.readonly:
                del(box[name])

    def modify(self, name, metadata):
        """
        Modify a document metadata
        """
        # Let's check if the document exist
        # It must be present in the index
        qp = QueryParser("hash", schema = self.index.schema)
        q = qp.parse(name)
        with self.index.searcher() as s:
            # No results
            if len(s.search(q)) == 0:
                raise IOError("Document does not exist")

        # So we do have a document, we just need to update it
        metadata['hash'] = name

        # Write everything into the index
        self.__update_index(metadata)

    def search(self, query):
        """
        Let's send a query to the shelf. The query is a dict of keys, with associated values.
        """
        qp = MultifieldParser(query.keys(), schema=self.index.schema)

        # Let's assemble the query
        search_terms = ''
        for k in query:
            search_terms += '%s:%s ' % (k, query[k])

        # We need to parse the query
        if u'*' in [ query[k] for k in query]:
            # We have a query asking for every doc
            q = Every()
        else:
            q = qp.parse(search_terms)

        # And now, we search
        results = self.index.searcher().search(q, limit=None)

        # We just have to return the results
        return results

    def get(self, name):
        """
        Let's return File like object from their names
        """
        for box in self.boxes:
            if name in box.keys():
                return box[name]
        return None


    def schema(self):
        """
        We want to return a dict associating fieldname to a list of relevant terms.
        """
        # We're going to parse through the index, we first need the field list, but we want only
        # the ones with scores
        fields = self.index.schema.scorable_names()
        schem = {}

        # We don't want all of the terms, just the most frequents ones
        with self.index.reader() as reader:
            schem = {field: [term for (a,term) in reader.most_frequent_terms(field, number=10)] for field in fields} 

        return schem
