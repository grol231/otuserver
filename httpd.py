from socket import *
s = socket(AF_INET, SOCK_STREAM)
s.bind(("", 9000))
s.listen(5)
while True:
    connection, address = s.accept()
    print("Received connection from: {}, connection: {}".format(address, connection))
    data = connection.recv(1024)
    if data:
        print(data)
        connection.close()

    #c.sendall("Hello %s\n" % a[0])
    #c.close()
