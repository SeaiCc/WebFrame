
#### mywerkzeug.serving.run_simple() (程序入口)
**核心参数**<br>
application: WSGIApplication <br>
request_handler: type[WSGIRequestHandler]

* mywerkzeug.serving.make_server()<br>
    **核心参数**<br>
    application: WSGIApplication<br>
    request_handler: type[WSGIRequestHandler]
    **返回**
    srv:BaseServer

    * mywerkzeug.serving.BaseWSGIServer()
        **核心参数**<br>
        app: WSGIApplication
        handler: type[WSGIRequestHandler]

        handler = mywerkzeug.serving.WSGIRequestHandler
        * mysocket.mysocketserver.TCPServer()
            **核心参数**<br>
            设置 RequestHandlerClass: type[WSGIRequestHandler]
            *初始化socket 绑定 启动socket*

        *IP端口绑定，ssl/address_family设置...*
        
* mysocket.mysocketserver.BaseWSGIServer.serve_forever()
    selector.select() loop 
    * self._handle_request_noblock()
    * self.process_request(request, client_address)
    * self.finish_request(request, client_address)
        *来一个select一个请求，创建一个Hanlder实例*
        *  mysocket.mysocketserver.StreamRequestHandler.__init__()
            self.setup() *设置socket/初始化wfile*
            mywerkzeug.serving.WSGIRequestHandler.handle()
            * myhttp.http_server.BaseHTTPRequestHandler.handle()
            * self.handle_one_request()
                mname = 'do_' + self.command
                method = getattr(self, mname) *获取子类WSGIRequestHandler属性方法*
                method() *调用，实际为WSGIRequestHandler.run_wsgi*
                * WSGIRequestHandler.run_wsgi
                    application_iter = app(environ, start_response)
                    *app为程序入口传递的由Request.application包装的处理方法*
                    *Request.application 使用Request(args[-2])创建请求对象，*
                    *调用start_response返回一个Response对象，然后调用Response(*args[-2:])*
                    start_response(status, headers) / return app_iter
                *遍历Response.__call__返回的迭代器，向self.wfile写入数据*


### BaseServer

    +------------+
    | BaseServer | (mywerkzeug.serving.BaseServer)
    +------------+
            |
            v
    +-----------+ 
    | TCPServer | (mysocket.mysocketserver.TCPServer)
    +-----------+ 

### WSGIRequestHandler

    +--------------------+
    | WSGIRequestHandler | (mywerkzeug.serving.WSGIRequestHandler)
    +--------------------+
                |
                v
    +------------------------+
    | BaseHTTPRequestHandler | (myhttp.http_server.BaseHTTPRequestHandler)
    +------------------------+ 
                |
                v
    +----------------------+
    | StreamRequestHandler | (mysocket.mysocketserver.StreamRequestHandler)
    +----------------------+
