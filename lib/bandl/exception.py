class BadDataError(Exception):
    def __init__(self, message):
        super(BadDataError, self).__init__(message)

class InvalidFileError(Exception):
    def __init__(self,message):
        super(InvalidFileError, self).__init__(message)