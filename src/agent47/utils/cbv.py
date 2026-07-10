from __future__ import annotations

import inspect
from typing import Any, Callable, Type, TypeVar, get_type_hints
from fastapi import APIRouter, Depends

T = TypeVar("T")

def cbv(router: APIRouter) -> Callable[[Type[T]], Type[T]]:
    """
    A class-based view decorator for FastAPI.
    Allows defining route methods inside a class, sharing dependencies 
    (like databases, authenticated users) via class attributes.
    """
    def decorator(cls: Type[T]) -> Type[T]:
        # Extract class-level type annotations to help construct correct signatures
        cls_annotations = get_type_hints(cls)
        
        # Identify all class-level properties that are FastAPI Depends instances
        class_dependencies = {}
        for name in dir(cls):
            if name.startswith("__"):
                continue
            val = getattr(cls, name)
            # Check if the class attribute is a Depends object
            if isinstance(val, Depends) or (hasattr(val, "__class__") and val.__class__.__name__ == "Depends"):
                class_dependencies[name] = val

        # Locate all routes currently registered on this router that match methods on the class
        routes_to_update = []
        for route in router.routes:
            endpoint = getattr(route, "endpoint", None)
            if endpoint and inspect.isfunction(endpoint) and endpoint.__name__ in dir(cls):
                routes_to_update.append(route)

        for route in routes_to_update:
            original_endpoint = route.endpoint
            
            # Inspect the original method's signature
            old_sig = inspect.signature(original_endpoint)
            parameters = list(old_sig.parameters.values())
            
            # Remove 'self' from the parameter list so FastAPI doesn't try to inject it
            if parameters and parameters[0].name == "self":
                parameters.pop(0)

            # Add class-level dependencies to the signature of this endpoint
            for name, val in class_dependencies.items():
                param = inspect.Parameter(
                    name=name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=val,
                    annotation=cls_annotations.get(name, inspect.Parameter.empty)
                )
                # Prevent duplicate parameters if they were already explicitly defined
                if not any(p.name == name for p in parameters):
                    parameters.append(param)

            # Build the new signature
            new_sig = inspect.Signature(parameters)

            # Create a wrapper function that extracts dependencies, instantiates the class,
            # and calls the original method on that instance.
            def make_wrapper(orig_endpoint=original_endpoint, class_deps=class_dependencies):
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    # Extract dependencies bound for class attributes
                    cls_kwargs = {}
                    for dep_name in class_deps:
                        if dep_name in kwargs:
                            cls_kwargs[dep_name] = kwargs.pop(dep_name)

                    # Instantiate the controller class
                    instance = cls()
                    
                    # Set the dependency attributes on the instance
                    for dep_name, dep_val in cls_kwargs.items():
                        setattr(instance, dep_name, dep_val)

                    # Execute the original method on the class instance
                    return orig_endpoint(instance, *args, **kwargs)
                return wrapper

            wrapper_func = make_wrapper()
            wrapper_func.__signature__ = new_sig
            wrapper_func.__name__ = original_endpoint.__name__
            wrapper_func.__doc__ = original_endpoint.__doc__

            # Update the router route to use the wrapper endpoint
            route.endpoint = wrapper_func

        return cls
    return decorator
