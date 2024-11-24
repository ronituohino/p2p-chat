#!/usr/bin/env python

import os
import errno

from shelves.boxes.box import Box

class FileBox(Box):
    """
    This box use the filesystem to store document. They're all stored in a 
    directory passed as an arg to __init__
    """
    path = None
    readonly = False

    def __init__(self, path):
        """
        We will test if the path exist, and if not creates it.
        """
        super(FileBox, self).__init__()

        self.path = os.path.abspath(path)
        # We do not have a directory
        try:
            os.mkdir(self.path)
        except IOError as e:
            raise e
        except OSError as e:
            error = errno.errorcode[e.errno]
            if error == 'EEXIST':
                # The file or directory already exist
                if os.path.isfile(self.path):
                    # And it's a file
                    raise e
            else:
                # Something else happened
                raise e

    def _list(self):
        """
        Return a list of files UUID in the FileBox
        """
        return [ unicode(item) for item in os.listdir(self.path)]

    def _put(self, name, document):
        """
        Put a document in the FileBox. name must be an a hash and document
        a File-like object
        """
        # Let's go back to the origi of file
        document.seek(0)

        # Let's open the destination, it will be created if needed
        # And let's write the origin in it by block of 4096bytes
        with open(os.path.join(self.path, unicode(name)), 'wb') as destination, document as origin:
            destination.write(origin.read())

    def _get(self, name):
        """
        Let's retrieve a file from the FileBox. name must be a hash and 
        we will return a File object
        """
        try:
            return open(os.path.join(self.path, unicode(name)), 'rb')
        except:
            raise IOError

    def _del(self, name):
        """
        Let's delete a file by its name
        """
        os.remove(os.path.join(self.path, unicode(name)))

