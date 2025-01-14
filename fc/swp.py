import enum
import logging
import llp
import queue
import struct
import threading

class SWPType(enum.IntEnum):
    DATA = ord('D')
    ACK = ord('A')

class SWPPacket:
    _PACK_FORMAT = '!BI'
    _HEADER_SIZE = struct.calcsize(_PACK_FORMAT)
    MAX_DATA_SIZE = 1400 # Leaves plenty of space for IP + UDP + SWP header

    def __init__(self, type, seq_num, data=b''):
        self._type = type
        self._seq_num = seq_num
        self._data = data

    @property
    def type(self):
        return self._type

    @property
    def seq_num(self):
        return self._seq_num

    @property
    def data(self):
        return self._data

    def to_bytes(self):
        header = struct.pack(SWPPacket._PACK_FORMAT, self._type.value,
                self._seq_num)
        return header + self._data

    @classmethod
    def from_bytes(cls, raw):
        header = struct.unpack(SWPPacket._PACK_FORMAT,
                raw[:SWPPacket._HEADER_SIZE])
        type = SWPType(header[0])
        seq_num = header[1]
        data = raw[SWPPacket._HEADER_SIZE:]
        return SWPPacket(type, seq_num, data)

    def __str__(self):
        return "%s %d %s" % (self._type.name, self._seq_num, repr(self._data))

class ListNode:
    def __init__(self, head, tail, data):
        self.head = head
        self.tail = tail
        self.data = data
        self.next = None


class SWPSender:
    _SEND_WINDOW_SIZE = 5
    _TIMEOUT = 1
    _LWS = 0
    _ACKD = 0
    semaphore = threading.Semaphore(_SEND_WINDOW_SIZE)
    buff = dict()
    timers = dict()

    def __init__(self, remote_address, loss_probability=0):
        self._llp_endpoint = llp.LLPEndpoint(remote_address=remote_address,
                loss_probability=loss_probability)

        # Start receive thread
        self._recv_thread = threading.Thread(target=self._recv)
        self._recv_thread.start()

        # TODO: Add additional state variables


    def send(self, data):
        for i in range(0, len(data), SWPPacket.MAX_DATA_SIZE):
            self._send(data[i:i+SWPPacket.MAX_DATA_SIZE])

    def _send(self, data):
        # TODO
        l = len(data)
        if(l == 0):
            return
        SWPSender.semaphore.acquire()
        seq_num = SWPSender._LWS
        SWPSender._LWS = SWPSender._LWS + l
        seq_tail = SWPSender._LWS
        SWPSender.buff[seq_tail] = data
        packet = SWPPacket(SWPType.DATA, seq_num, data)
        packet_byte = packet.to_bytes()
        self.timers[seq_tail]\
            = threading.Timer(SWPSender._TIMEOUT, self._retransmit, [seq_num, seq_tail])
        self.timers[seq_tail].start()
        self._llp_endpoint.send(packet_byte)
        return

    def _retransmit(self, seq_num, seq_tail):
        # TODO
        if(seq_tail <= SWPSender._ACKD):
            return
        packet = SWPPacket(SWPType.DATA, seq_num, SWPSender.buff[seq_tail])
        packet_byte = packet.to_bytes()
        self.timers[seq_tail]\
            = threading.Timer(SWPSender._TIMEOUT, self._retransmit, [seq_num, seq_tail])
        self.timers[seq_tail].start()
        self._llp_endpoint.send(packet_byte)
        return

    def _recv(self):
        while True:
            # Receive SWP packet
            raw = self._llp_endpoint.recv()
            if raw is None:
                continue
            packet = SWPPacket.from_bytes(raw)
            logging.debug("Received: %s" % packet)

            # TODO
            if(packet._type != SWPType.ACK):
                continue;
            if(packet._seq_num > SWPSender._ACKD):
                SWPSender._ACKD = packet._seq_num
            self.timers[packet._seq_num].cancel()
            for key in [key for key in SWPSender.buff.keys() if key <= SWPSender._ACKD]:
                del SWPSender.buff[key]
                SWPSender.semaphore.release()
        return

class SWPReceiver:
    _RECV_WINDOW_SIZE = 5
    _ACKD = 0
    buffer_head = ListNode(-1, -1, None)
    semaphore = threading.Semaphore(_RECV_WINDOW_SIZE)

    def __init__(self, local_address, loss_probability=0):
        self._llp_endpoint = llp.LLPEndpoint(local_address=local_address,
                loss_probability=loss_probability)

        # Received data waiting for application to consume
        self._ready_data = queue.Queue()

        # Start receive thread
        self._recv_thread = threading.Thread(target=self._recv)
        self._recv_thread.start()

        # TODO: Add additional state variables


    def recv(self):
        return self._ready_data.get()

    def _recv(self):
        while True:
            # Receive data packet
            SWPReceiver.semaphore.acquire()
            raw = self._llp_endpoint.recv()
            packet = SWPPacket.from_bytes(raw)
            logging.debug("Received: %s" % packet)

            # TODO
            if(packet._seq_num + len(packet._data) <= SWPReceiver._ACKD):
                packet = SWPPacket(SWPType.ACK, SWPReceiver._ACKD)
                packet_byte = packet.to_bytes()
                self._llp_endpoint.send(packet_byte)
                SWPReceiver.semaphore.release()
                continue
            head = packet._seq_num
            tail = head + len(packet._data)
            self.insert_chunk(ListNode(head, tail, packet._data))
            c = SWPReceiver.buffer_head.next
            cur = SWPReceiver.buffer_head.next
            while(cur is not None and cur.head == SWPReceiver._ACKD):
                self._ready_data.put(cur.data)
                SWPReceiver._ACKD = cur.tail
                cur = cur.next
            SWPReceiver.buffer_head.next = cur
            packet = SWPPacket(SWPType.ACK, SWPReceiver._ACKD)
            packet_byte = packet.to_bytes()
            self._llp_endpoint.send(packet_byte)
            SWPReceiver.semaphore.release()

        return

    def insert_chunk(self, node):
        cur = SWPReceiver.buffer_head
        while(cur is not None):
            if(node.head  < cur.tail):
                return
            elif(cur.next is None or cur.next.head >= node.tail):
                cur.next = node
                return
            else:
                cur = cur.next
        return
