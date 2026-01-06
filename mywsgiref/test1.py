from mywsgiref.simple_server import make_server

def hello_world_app(environ, start_response):
    status = '200 OK'  # HTTP Status
    headers = [('Content-type', 'text/plain; charset=utf-8')]  # HTTP Headers
    start_response(status, headers)

    # The returned object is going to be printed
    return [b"Hello World"]

with make_server('', 18000, hello_world_app) as httpd:
    print("Serving on port 18000...")

    # Serve until process is killed
    httpd.serve_forever()