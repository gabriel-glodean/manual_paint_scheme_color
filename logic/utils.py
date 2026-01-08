import time


def log_exec_time(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"[timing] {func.__name__} executed in {elapsed:.4f} seconds")
        return result
    return wrapper