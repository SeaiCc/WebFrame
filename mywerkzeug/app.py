import sys
sys.path.append("/media/ubuntu/data/gitSourceCode/WebFrame")
# from werkzeug.wrappers import Request, Response
from mywerkzeug.wrappers import Request, Response


@Request.application
def application(request: Request) -> Response:
    return Response("Hello, World!")

if __name__ == "__main__":
    # from werkzeug.serving import run_simple
    from mywerkzeug.serving import run_simple
    run_simple("127.0.0.1", 5000, application)