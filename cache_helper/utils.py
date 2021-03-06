from hashlib import sha256
import inspect

from cache_helper import settings
from cache_helper.exceptions import CacheKeyCreationError
from cache_helper.interfaces import CacheHelperCacheable


def get_function_cache_key(func_type, func_name, func_args, func_kwargs):
    if func_type in ['method', 'function']:
        args_string = _sanitize_args(*func_args, **func_kwargs)
    elif func_type == 'class_method':
        # In this case, since we are dealing with a class method, the first arg to the function
        # will be the class. Since the name of the class and function is already built in to the
        # cache key, we can bypass the class variable and instead slice from the first index.
        args_string = _sanitize_args(*func_args[1:], **func_kwargs)
    key = '{func_name}{args_string}'.format(func_name=func_name, args_string=args_string)
    return key


def get_hashed_cache_key(key):
    """
    Given the intermediate key produced by a function call along with its args + kwargs,
    performs a sha256 hash on the utf-8 encoded version of the key, and returns the result
    """
    key_hash = sha256(key.encode('utf-8', errors='ignore')).hexdigest()
    return key_hash


def _sanitize_args(*args, **kwargs):
    """
    Creates unicode key from all kwargs/args
        -Note: comma separate args in order to prevent foo(1,2), foo(12, None) corner-case collisions...
    """
    key = ";{args_key};{kwargs_key}"
    args_key = _plumb_collections(args)
    kwargs_key = _plumb_collections(kwargs)
    return key.format(args_key=args_key, kwargs_key=kwargs_key)


def get_function_type(func):
    """
    Gets the type of the given function
    """
    if 'self' in inspect.getargspec(func).args:
        return 'method'
    if 'cls' in inspect.getargspec(func).args:
        return 'class_method'

    if inspect.isfunction(func):
        return 'function'

    return None


def get_function_name(func):
    func_type = get_function_type(func)

    if func_type in ['method', 'class_method', 'function']:
        name = '{func_module}.{qualified_name}'\
            .format(func_module=func.__module__, qualified_name=func.__qualname__)
        return name

    return None


def _plumb_collections(input_item):
    """
    Rather than enforce a list input type, place ALL input
    in our state list.
    """
    level = 0
    return_list = []
    # really just want to make sure we start off with a list of iterators, so enforce here
    if hasattr(input_item, '__iter__'):
        if isinstance(input_item, dict):
            # Py3k Compatibility nonsense...
            remains = [[(k, v) for k, v in input_item.items()].__iter__()]
            # because dictionary iterators yield tuples, it would appear
            # to be 2 levels per dictionary, but that seems unexpected.
            level -= 1
        else:
            remains = [input_item.__iter__()]
    else:
        return _get_object_cache_key(input_item)

    while len(remains) > 0:
        if settings.MAX_DEPTH is not None and level > settings.MAX_DEPTH:
            raise CacheKeyCreationError(
                'Function args or kwargs have too many nested collections for current MAX_DEPTH')
        current_iterator = remains.pop()
        level += 1
        while True:
            try:
                current_item = next(current_iterator)
            except StopIteration:
                level -= 1
                break
            # In py3k hasattr(str, '__iter__')  => True but in python 2 it's False which will break
            # this if statement. That's why we do `not isinstance(current_item, str)` check as well.
            if hasattr(current_item, '__iter__') and not isinstance(current_item, str):
                return_list.append(',')

                # Dictionaries and sets are unordered and can be of various data types
                # We use the sha256 hash on keys and sort to be deterministic
                if isinstance(current_item, dict):
                    hashed_list = []

                    for k, v in current_item.items():
                        item_cache_key = _get_object_cache_key(k)
                        hashed_list.append((sha256(item_cache_key.encode('utf-8')).hexdigest(), v))

                    hashed_list = sorted(hashed_list, key=lambda t: t[0])
                    remains.append(current_iterator)
                    remains.append(hashed_list.__iter__())

                    level -= 1
                    break
                elif isinstance(current_item, set):
                    hashed_list = []

                    for item in current_item:
                        item_cache_key = _get_object_cache_key(item)
                        hashed_list.append(sha256(item_cache_key.encode('utf-8')).hexdigest())

                    hashed_list = sorted(hashed_list)
                    remains.append(current_iterator)
                    remains.append(hashed_list.__iter__())
                    break
                else:
                    remains.append(current_iterator)
                    remains.append(current_item.__iter__())
                    break
            else:
                current_item_string = '{0},'.format(_get_object_cache_key(current_item))
                return_list.append(current_item_string)
                continue
    # trim trailing comma
    return_string = ''.join(return_list)
    # trim last ',' because it lacks significant meaning.
    return return_string[:-1]


def _get_object_cache_key(obj):
    """
    Function used to get the individual cache key for objects. Checks if the
    object is an instance of CacheHelperCacheable, which means it will have a
    get_cache_helper_key function defined for it which will be used as the key.
    Otherwise, just uses the string representation of the object.
    """
    if isinstance(obj, CacheHelperCacheable):
        return obj.get_cache_helper_key()
    else:
        return str(obj)
