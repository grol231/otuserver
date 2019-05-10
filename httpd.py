import socket
import time
import os
import shutil
import posixpath
import argparse
import logging
import urllib
import threading
import selectors
from multiprocessing import Process, current_process


class BaseServer:
    timeout = None

    def __init__(self, server_address, RequestHandlerClass):
        self.server_address = server_address
        self.RequestHandlerClass = RequestHandlerClass
        self.__is_shut_down = threading.Event()
        self.__shutdown_request = False

    def server_activate(self):
        pass

    def serve_forever(self, poll_interval=0.5):
        self.__is_shut_down.clear()
        try:
            with selectors.PollSelector() as selector:
                selector.register(self, selectors.EVENT_READ)

                while not self.__shutdown_request:
                    ready = selector.select(poll_interval)
                    if ready:
                        self._handle_request_noblock()
        finally:
            self.__shutdown_request = False
            self.__is_shut_down.set()

    def shutdown(self):
        self.__shutdown_request = True
        self.__is_shut_down.wait()

    def _handle_request_noblock(self):
        try:
            request, client_address = self.get_request()
        except OSError:
            return
        self.process_request(request, client_address)

    def process_request(self, request, client_address):
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except:
            self.handle_error(request, client_address)
            self.shutdown_request(request)

    def server_close(self):
        pass

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(request, client_address, self)

    def shutdown_request(self, request):
        self.close_request(request)

    def close_request(self, request):
        request.close()

    def handle_error(self, request, client_address):
        print('-'*40)
        print('Exception happened during processing of request from', end=' ')
        print(client_address)
        import traceback
        traceback.print_exc()
        print('-'*40)


class OTUServer(BaseServer):

    address_family = socket.AF_INET

    socket_type = socket.SOCK_STREAM

    request_queue_size = 5

    allow_reuse_address = False

    document_root = None

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass)
        self.socket = socket.socket(self.address_family,
                                    self.socket_type)
        if bind_and_activate:
            try:
                self.server_bind()
                self.server_activate()
            except:
                self.server_close()
                raise

    def server_bind(self):
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def server_activate(self):
        self.socket.listen(self.request_queue_size)

    def server_close(self):
        self.socket.close()

    def fileno(self):
        return self.socket.fileno()

    def get_request(self):
        return self.socket.accept()

    def shutdown_request(self, request):
        try:
            request.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.close_request(request)

    def set_document_root(self, document_root):
        self._document_root = document_root

    def get_document_root(self):
        return self._document_root


class BaseRequestHandler:
    def __init__(self, request, client_address, server):
        logging.info('current process: {}'.format(current_process().name))
        self.request = request
        self.client_address = client_address
        self.server = server
        self.setup()
        try:
            self.handle()
        finally:
            self.finish()

    def setup(self):
        pass

    def handle(self):
        pass

    def finish(self):
        pass


class StreamRequestHandler(BaseRequestHandler):
    rbufsize = -1
    wbufsize = 0

    def setup(self):
        self.connection = self.request
        self.rfile = self.connection.makefile('rb', self.rbufsize)
        self.wfile = self.connection.makefile('wb', self.wbufsize)

    def finish(self):
        if not self.wfile.closed:
            try:
                self.wfile.flush()
            except socket.error:
                pass
        self.wfile.close()
        self.rfile.close()


class BaseHTTPRequestHandler(StreamRequestHandler):

    def __int__(self, request, client_address, server):
        super().__int__(request, client_address, server)

    def handle(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(405, 'Method Not Allowed')
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
        except socket.timeout as e:
            return

    def send_error(self, code, message):
        self.send_response_only(code, message)
        self.send_header('Server', 'OTUServer')
        self.send_header('Date', self.date_time_string())
        self.end_headers()

    def send_response_only(self, code, message=None):
        if not hasattr(self, '_headers_buffer'):
            self._headers_buffer = []
        self._headers_buffer.append(("%s %d %s\r\n" %
                                     (self.protocol_version_string(), code, message)).encode('latin-1'))

    def send_header(self, keyword, value):
        if not hasattr(self, '_headers_buffer'):
            self._headers_buffer = []
        self._headers_buffer.append(
            ("%s: %s\r\n" % (keyword, value)).encode('latin-1'))

    def end_headers(self):
        self._headers_buffer.append(b"\r\n")
        self.flush_headers()

    def flush_headers(self):
        if hasattr(self, '_headers_buffer'):
            self.wfile.write(b"".join(self._headers_buffer))
            self._headers_buffer = []

    def parse_request(self):
        requestline = str(self.raw_requestline, 'iso-8859-1')
        requestline = requestline.rstrip('\r\n')
        self.requestline = requestline
        words = requestline.split()
        if len(words) == 3:
            command = words[0]
            path = words[1]
            version = words[2]
        elif len(words) == 2:
            command, path = words
            if command != 'GET':
                self.send_error(405, 'Method Not Allowed')
                return False
        elif not words:
            return False
        else:
            self.send_error(405, 'Method Not Allowed')
            return False

        self.command, self.path , self.version = command, path, version
        return True


class HTTPRequestHandler(BaseHTTPRequestHandler):
    extensions_map = {
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'text/javascript',
        '.jpeg': 'image/jpeg',
        '.jpg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.swf': 'application/x-shockwave-flash',
        '.txt': 'text/plain'
    }
    _document_root = None

    def __init__(self, request, client_address, server):
        self._document_root = server.get_document_root()
        super().__init__(request, client_address, server)
        self.server = server

    def do_GET(self):
        f = self.send_head()
        if f:
            try:
                self.copyfile(f, self.wfile)
            finally:
                f.close()

    def do_HEAD(self):
        f = self.send_head()
        if f:
            f.close()

    def send_head(self):
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            if path[-1:] is not '/':
                self.send_error(405, 'Method Not Allowed')
                return None

            index = "index.html"
            index = os.path.join(path, index)
            if os.path.exists(index):
                path = index
            else:
                self.send_error(404, 'Not Found')
                return None

        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, 'Not Found')
            return None
        try:
            self.send_response_only(200, "OK")
            self.send_header("Content-Type", ctype)
            fs = os.fstat(f.fileno())
            self.send_header("Content-Length", str(fs[6]))
            self.send_header('Connection', 'close')
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def send_response(self, code, msg):
        self.send_response_only(code, msg)
        self.send_header('Server', 'OTUServer')
        self.send_header('Date', self.date_time_string())

    def protocol_version_string(self):
        return self.version

    def date_time_string(self, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
        s = "%02d %3d %4d %02d:%02d:%02d GMT" % (
                day, month, year,
                hh, mm, ss)
        return s

    def guess_type(self, path):
        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return ''

    def copyfile(self, source, outputfile):
        shutil.copyfileobj(source, outputfile)

    def translate_path(self, path):
        logging.info(path)
        path = path.split('?', 1)[0]
        trailing_slash = path.rstrip().endswith('/')
        try:
            path = urllib.parse.unquote(path, errors='surrogatepass')
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        words = path.split('/')
        words = filter(None, words)
        if hasattr(self, '_document_root') and self._document_root is not None:
            path = self._document_root
        else:
            path = os.getcwd()
        for word in words:
            if os.path.dirname(word) or word in (os.curdir, os.pardir):
                # Ignore components that are not a simple file/directory name
                continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path


def serve_forever(server):
    try:
        server.serve_forever()
    except Exception as e:
        logging.error(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', dest='document_root', required=False)
    parser.add_argument('-w', dest='worker_number', required=False, default=1)
    args = parser.parse_args()
    logging.basicConfig(format='[%(asctime)s] %(levelname).1s %(message)s', level=logging.INFO,
                        datefmt='%Y.%m.%d %H:%M:%S', filename="")
    HOST, PORT = "localhost", 8080
    worker_number = int(args.worker_number)

    server = OTUServer((HOST, PORT), HTTPRequestHandler)
    server.set_document_root(args.document_root)

    for i in range(worker_number):
        p = Process(target=serve_forever, args=(server,))
        p.daemon = True
        p.start()
        logging.info(p)
    try:
        logging.info('server run')
        server.serve_forever()
    finally:
        logging.info('server stop')
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(e)


