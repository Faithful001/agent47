import json
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from fastapi.responses import JSONResponse

class ResponseInterceptor(BaseHTTPMiddleware):
    """
    Middleware that intercepts all JSON responses and formats them into a standardized structure:
    {
        "success": bool,
        "message": str,
        "data": Any | None
    }
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip intercepting OpenAPI schema and docs to prevent breaking Swagger UI
        if request.url.path in ["/openapi.json", "/docs", "/redoc"]:
            return await call_next(request)
            
        response = await call_next(request)
        
        if response.headers.get("content-type") == "application/json":
            # Extract the raw body chunks
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            
            try:
                data = json.loads(body.decode("utf-8"))
            except ValueError:
                data = body.decode("utf-8")
                
            success = 200 <= response.status_code < 400
            
            # Extract or default the message
            message = "Success" if success else "An error occurred"
            
            # Handle standard FastAPI error formats or custom message keys
            if isinstance(data, dict):
                # FastAPI validation errors or HTTPExceptions
                if "detail" in data:
                    detail = data.pop("detail")
                    if isinstance(detail, list):
                        # Pydantic 422 validation error
                        message = "Validation Error"
                        data = detail  # Provide the list of errors as the data
                    elif isinstance(detail, str):
                        message = detail
                
                # If there's an explicit "message" key in the original response
                if "message" in data:
                    message = data.pop("message")

                # If there's an explicit "data" key, unwrap it to preventing double-nesting
                if "data" in data and len(data) == 1:
                    data = data["data"]

                # If the dict is now empty after popping detail/message, set it to None
                if isinstance(data, dict) and not data:
                    data = None

            # Standardize the structure
            formatted_content = {
                "success": success,
                "message": message,
                "data": data
            }
            
            # Remove content-length since the payload was mutated and the length will differ
            headers = dict(response.headers)
            if "content-length" in headers:
                del headers["content-length"]
                
            return JSONResponse(
                content=formatted_content,
                status_code=response.status_code,
                headers=headers
            )

        return response
