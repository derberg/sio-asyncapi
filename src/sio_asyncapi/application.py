import inspect
from typing import Callable, Optional, Type, List, Union
from flask import Flask
from flask_socketio import SocketIO
from pydantic import BaseModel, ValidationError
from sio_asyncapi.asyncapi.docs import AsyncAPIDoc, NotProvidedType
from loguru import logger

class RequestValidationError(Exception):
    pass

class ResponseValidationError(Exception):
    pass

class AsyncAPISocketIO(SocketIO):
    """Inherits the :class:`flask_socketio.SocketIO` class.
    Adds ability to validate with pydantic models.

    Example::
        socket = AsyncAPISocketIO(app, async_mode='threading', logger=True)
        class TokenModel(BaseModel):
            token: int

        class RequestTokenModel(BaseModel):
            type: "str"

        @socket.on('get_token', response_model=TokenModel, request_model=RequestTokenModel)
        def get_token(message):
            return {"token": 1234}
    """

    def __init__(
        self,
        app: Optional[Flask] = None,
        /,
        validate: bool = True,
        generate_docs: bool = False,
        version: str = "1.0.0",
        title: str = "Demo Chat API",
        description: str = "Demo Chat API",
        server_url: str = "http://localhost:5000",
        server_name: str = "BACKEND",
        **kwargs,
    ):
        """Create AsycnAPISocketIO

        Args:
            app (Optional[Flask]): flask app
            validation (bool, optional): If True request and response will be validated. Defaults to True.
            generate_docs (bool, optional): If True AsyncAPI specs will be generated. Defaults to False.
            doc_template (Optional[str], optional): AsyncAPI YMAL template. Defaults to None.
            version (str, optional): AsyncAPI version. Defaults to "1.0.0".
            title (str, optional): AsyncAPI title. Defaults to "Demo Chat API".
            description (str, optional): AsyncAPI description. Defaults to "Demo Chat API".
            server_url (str, optional): AsyncAPI server url. Defaults to "http://localhost:5000".
            server_name (str, optional): AsyncAPI server name. Defaults to "BACKEND".
        """
        self.validate = validate
        self.generate_docs = generate_docs
        self.asyncapi_doc: AsyncAPIDoc = \
            AsyncAPIDoc.default_init(
                version=version,
                title=title,
                description=description,
                server_url=server_url,
                server_name=server_name,
            )
        super().__init__(app=app, **kwargs)


    def on_error_default(self, *args, **kwargs):
        """Decorator to register a SocketIO error handler with additional
        functionalities.  If no arguments default Flask-SocketIO error handler
        if `model` is provided it's used for generating AsyncAPI spec and validation.

        Example::

            @socketio.on_error_default(model=SocketError)
            def default_error_handler(e):
                pass
        Args:
            model (Optional[BaseModel], optional): pydantic model. Defaults to None.

        """
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # the decorator was invoked without arguments
            # args[0] is the decorated function
            return super().on_error_default(args[0])
        else:
            # the decorator was invoked with arguments
            assert kwargs.get("model") is not None, "model is required"
            # TODO: add to spec and validation here
            _super = super()
            def set_on_error_default(exception_handler):
                return _super.on_error_default(exception_handler)

            return set_on_error_default

    def on(
            self,
            message,
            namespace=None,
            *,
            get_from_typehint: bool = False,
            response_model: Optional[Union [Type[BaseModel], NotProvidedType]] = None,
            request_model: Optional[Union [Type[BaseModel], NotProvidedType]] = None,
    ):
        """Decorator to register a SocketIO event handler with additional functionalities

        Args:
            message (str): refer to SocketIO.on(message)
            namespace (str, optional): refer to SocketIO.on(namespace). Defaults to None.
            get_from_typehint (bool, optional): Get request and response models from typehint.
                request_model and response_model take precedence over typehints if not None.
                Defaults to False.
            response_model (Optional[Type[BaseModel]], optional): Acknowledge model used
                for validation and documentation. Defaults to None.
            request_model (Optional[Type[BaseModel]], optional): Request payload model used
                for validation and documentation. Defaults to None.
        """
        def decorator(handler: Callable):

            nonlocal request_model
            nonlocal response_model
            if get_from_typehint:
                try:
                    first_arg_name = inspect.getfullargspec(handler)[0][0]
                except IndexError:
                    posible_request_model = None
                else:
                    posible_request_model = handler.__annotations__.get(first_arg_name, "NotProvided")
                posible_response_model = handler.__annotations__.get("return", "NotProvided")
                if request_model is None:
                    request_model = posible_request_model # type: ignore
                if response_model is None:
                    response_model = posible_response_model # type: ignore

            # print(f"request_model: {request_model}")
            # print(f"response_model: {response_model}")

            if self.generate_docs:
                self.asyncapi_doc.add_new_receiver(
                    handler,
                    message,
                    ack_data_model=response_model,
                    payload_model=request_model,
                )

            def wrapper(*args, **kwargs):
                new_handler = self._handle_all(
                    request_model=request_model,
                    response_model=response_model
                )(handler)
                return new_handler(*args, **kwargs)

            # Decorate with SocketIO.on decorator
            super(AsyncAPISocketIO, self).on(message, namespace)(wrapper)
            return wrapper
        return decorator

    def _handle_all(self,
                    response_model: Optional[Union [Type[BaseModel], NotProvidedType]] = None,
                    request_model: Optional[Union [Type[BaseModel], NotProvidedType]] = None,
                    ):
        """Decorator to validate request and response with pydantic models
        Args:
            handler (Callable, optional): handler function. Defaults to None.
            response_model (Optional[Type[BaseModel]], optional): Acknowledge model used
                for validation and documentation. Defaults to None.
            request_model (Optional[Type[BaseModel]], optional): Request payload model used
                for validation and documentation. Defaults to None.

        Raises: RequestValidationError, ResponseValidationError
        """

        def decorator(handler: Callable):

            def wrapper(*args, **kwargs):
                request = args[0] if len(args) > 0 else None
                if not request:
                    request = kwargs.get("request")
                if request:
                    try:
                        if self.validate and request_model and isinstance(request_model, type(BaseModel)):
                            request_model.validate(request) # type: ignore
                    except ValidationError as e:
                        logger.error(f"ValidationError for incoming request: {e}")
                        raise RequestValidationError(e)

                    response = handler(*args, **kwargs)
                    try:
                        if self.validate and response_model and isinstance(response_model, type(BaseModel)):
                            response_model.validate(response) # type: ignore
                    except ValidationError as e:
                        logger.error(f"ValidationError for outgoing response: {e}")
                        raise ResponseValidationError(e)

                    if isinstance(response, BaseModel):
                        return response.json()
                    else:
                        return response
                else:
                    return handler(*args, **kwargs)

            return wrapper
        return decorator