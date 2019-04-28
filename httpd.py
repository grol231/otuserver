import socket
import time
import os
import shutil
import posixpath
import argparse
from socketserver import TCPServer
from socketserver import StreamRequestHandler
import urllib
from queue import Queue
from threading import Thread


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


class ThreadingMixIn:
    def set_pool(self, pool):
        self._pool = pool

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except:
            self.handle_error(request, client_address)
            self.shutdown_request(request)

    def process_request(self, request, client_address):
        self._pool.add_task(self.process_request_thread, request, client_address)


class HTTPServer(ThreadingMixIn, TCPServer):
    pass


class OTUServer(HTTPServer):
    _document_root = None

    def set_document_root(self, document_root):
        self._document_root = document_root

    def get_document_root(self):
        return self._document_root


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


class Worker(Thread):
    def __init__(self, tasks):
        Thread.__init__(self)
        self.tasks = tasks
        self.daemon = True
        self.start()

    def run(self):
        while True:
            func, args, kargs = self.tasks.get()
            try:
                func(*args, **kargs)
            except Exception as e:
                print(e)
            finally:
                self.tasks.task_done()


class ThreadPool:
    def __init__(self, num_threads):
        self.tasks = Queue(num_threads)
        for _ in range(num_threads):
            Worker(self.tasks)

    def add_task(self, func, *args, **kargs):
        self.tasks.put((func, args, kargs))

    def wait_completion(self):
        self.tasks.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', dest='document_root', required=False)
    parser.add_argument('-w', dest='worker_number', required=False, default=1)
    args = parser.parse_args()

    HOST, PORT = "localhost", 8080
    worker_number = int(args.worker_number)
    pool = ThreadPool(worker_number)

    server = OTUServer((HOST, PORT), HTTPRequestHandler)
    server.set_document_root(args.document_root)
    server.set_pool(pool)
    try:
        print('server run')
        server.serve_forever()
    finally:
        print('server stop')
        pool.wait_completion()
        server.server_close()
