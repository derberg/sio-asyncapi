import abc
from loguru import logger
from flask import Flask
from sio_asyncapi import AsyncAPISocketIO, ResponseValidationError, RequestValidationError
from pydantic import BaseModel, Field, AnyUrl
from pydantic import BaseModel, Field, AnyUrl
from typing import Optional
from pathlib import Path
import pathlib

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

# socketio = SocketIO(app, async_mode=async_mode)
socketio = AsyncAPISocketIO(
    app,
    async_mode=async_mode,
    logger=logger,
    validate=True,
    generate_docs=True,
    version="1.0.0",
    title="Downloader API",
    description="Server downloader API",
    server_url="http://localhost:5000",
    server_name="DOWNLOADER_BACKEND",
)

from engineio.payload import Payload
Payload.max_decode_packets = 16

class AnyModel(BaseModel):
    pass

class SocketBaseResponse(BaseModel, abc.ABC):
    """Base model for all responses"""
    success: bool = Field(True, description="Success status" )
    error: Optional[str] = Field(
        None,
        description="Error message if any",
        example="Invalid request")


class SocketErrorResponse(SocketBaseResponse):
    """Error response"""
    success: bool = False
    error: str = Field(..., description="Error message if any", example="Invalid request")

class DownloadFileRequest(BaseModel):
    url: AnyUrl = Field(...,
        description="URL to download",
        example="https://cdn.pixabay.com/photo/2015/04/23/22/00/tree-736885__480.jpg")
    location: Path = Field(...,
        description="Destination local to file system; should be an absolute path",
        example="/tmp/tree.jpg")
    check_hash: Optional[bool] = False

class DownloadAccepted(SocketBaseResponse):
    class Data(BaseModel):
        is_accepted: bool = True
    data: Data


downloader_queue = []
@socketio.on('download_file', get_from_typehint=True)
def download_file(request: DownloadFileRequest) -> DownloadAccepted:
    """Download a file from a URL to a server file system"""
    # check if file exists
    request = DownloadFileRequest.parse_obj(request)
    if pathlib.Path(request.location).exists():
        return DownloadAccepted(
            success=False,
            data=DownloadAccepted.Data(
                is_accepted=False),
            error="File already exists")
    else:
        # add to queue
        downloader_queue.append(request)
        return DownloadAccepted(data=DownloadAccepted.Data(is_accepted=True))


@socketio.on_error_default(model=SocketBaseResponse)
def default_error_handler(e):
    if isinstance(e, RequestValidationError):
        logger.error(f"Request validation error: {e}")
        return SocketErrorResponse(error=str(e)).json()
    elif isinstance(e, ResponseValidationError):
        logger.critical(f"Response validation error: {e}")
        raise e
    else:
        logger.critical(f"Unknown error: {e}")
        raise e

if __name__ == '__main__':
    socketio.run(app, debug=True)



# # Generate and save AsycnAPI [https://studio.asyncapi.com/] specification in ./asyncapi_2.5.0.yml
# # Usage: python asycnapi_save_doc
# import pathlib
# FILE_NAME = "downloader.yml"

# if __name__ == "__main__":
#     path = pathlib.Path(__file__).parent / FILE_NAME
#     doc_str = socketio.asyncapi_doc.get_yaml()
#     with open(path, "w") as f:
#         # doc_str = spec.get_json_str_doc()
#         f.write(doc_str)
#     print(doc_str)