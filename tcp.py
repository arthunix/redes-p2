import asyncio
import random
from time import time
from math import ceil
from tcputils import *


class Servidor:
    def __init__(self, rede, porta):
        self.rede = rede
        self.porta = porta
        self.conexoes = {}
        self.callback = None
        self.rede.registrar_recebedor(self._rdt_rcv)

    def registrar_monitor_de_conexoes_aceitas(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que uma nova conexão for aceita
        """
        self.callback = callback

    def _rdt_rcv(self, src_addr, dst_addr, segment):
        src_port, dst_port, seq_no, ack_no, \
            flags, window_size, checksum, urg_ptr = read_header(segment)
        if dst_port != self.porta:
            return

        if not self.rede.ignore_checksum and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('descartando segmento com checksum incorreto')
            return

        payload = segment[4*(flags>>12):]
        id_conexao = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            # A flag SYN estar setada significa que é um cliente tentando estabelecer uma conexão nova
            # TODO: talvez você precise passar mais coisas para o construtor de conexão
            conexao = self.conexoes[id_conexao] = Conexao(self, id_conexao, seq_no + 1)

            # TODO: você precisa fazer o handshake aceitando a conexão. Escolha se você acha melhor
            # fazer aqui mesmo ou dentro da classe Conexao.
            if self.callback:
                self.callback(conexao)
            
            conexao._send_flag(FLAGS_SYN | FLAGS_ACK)
        elif id_conexao in self.conexoes:
            conexao = self.conexoes[id_conexao]
            if (flags & (FLAGS_ACK | FLAGS_FIN)) == FLAGS_ACK | FLAGS_FIN:
                conexao.ack_no += 1
                conexao.callback(self, b'')
                conexao._send_flag(FLAGS_ACK)
                del self.conexoes[id_conexao]
            else:
                self.conexoes[id_conexao]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))


class Conexao:
    def __init__(self, servidor, id_conexao, ack_no):
        self.servidor = servidor
        self.id_conexao = id_conexao
        self.callback = None
        self.seq_no = random.randint(0, 0xffff)
        self.ack_no = ack_no
        self.next = 0
        self.timer = None
        self.time_interval = 1
        self.EstimatedRTT = None
        self.DevRTT = None
        self.SampleRTT = None
        self.fin_ack = False
        self.unsent_data = b''
        self.unacked_data = b''
        self.T0 = None
        self.Retry = 0 
        self.window_size = 1
        self.increase_window_size = False
        # self.timer = asyncio.get_event_loop().call_later(1, self._exemplo_timer)  # um timer pode ser criado assim; esta linha é só um exemplo e pode ser removida
        # self.timer.cancel()   # é possível cancelar o timer chamando esse método; esta linha é só um exemplo e pode ser removida

    def _send_flag(self, pflag):
        flags = 0 ^ 0
        flags = flags | (pflag)

        client_addr, client_port, server_addr, server_port = self.id_conexao
        pass_2_handshake_header = make_header(server_port, client_port, self.seq_no, self.ack_no, flags)
        pass_2_handshake_header = fix_checksum(pass_2_handshake_header, server_addr, client_addr)
        self.servidor.rede.enviar(pass_2_handshake_header, client_addr)

        if pflag == ( FLAGS_SYN | FLAGS_ACK ):
            self.seq_no += 1

    def _start_timer(self):
        self._stop_timer()
        self.timer = asyncio.get_event_loop().call_later(self.time_interval, self._timer_timeout)

    def _stop_timer(self):
        if self.timer != None:
            self.timer.cancel()

    def _timer_timeout(self):
        self.Retry += 1
        self.window_size = ceil(self.window_size / 2)
        self.window_size = self.window_size if self.window_size != 0 else 1
        self._resend()

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        # TODO: trate aqui o recebimento de segmentos provenientes da camada de rede.
        # Chame self.callback(self, dados) para passar dados para a camada de aplicação após
        # garantir que eles não sejam duplicados e que tenham sido recebidos em ordem.
        print('recebido payload: %r' % payload)

        if seq_no == self.ack_no:
            if len(payload) > 0:
                self.ack_no += len(payload)
                self.callback(self, payload)
                self._send_flag(FLAGS_ACK)

            if len(self.unacked_data) > 0:
                if self.T0 != None:
                    SampleRTT = time() - self.T0
                    if self.EstimatedRTT == None:
                        self.EstimatedRTT = SampleRTT
                        self.DevRTT = SampleRTT / 2
                    else:
                        alpha = 0.125
                        beta = 0.25
                        self.EstimatedRTT = (1 - alpha) * self.EstimatedRTT + alpha * SampleRTT
                        self.DevRTT = (1 - beta) * self.DevRTT + beta * abs(SampleRTT - self.EstimatedRTT)
                    self.time_interval = self.EstimatedRTT + 4 * self.DevRTT

                self._stop_timer()

                if ack_no == self.next:
                    self.unacked_data = b''
                    self.seq_no = self.next

                    if self.increase_window_size and self.Retry == 0:
                        self.window_size += 1
                        self.increase_window_size = False
                    
                    if len(self.unsent_data) > 0:
                        self.enviar(None)
                    self.Retry = 0

                elif self.Retry > 0:
                    self.unacked_data = self.unacked_data[MSS:]
                    self.seq_no += MSS
                    if len(self.unacked_data) > 0:
                        self._resend()      
                    else:
                        self.Retry = 0

    def _resend(self):
        self.T0 = None

        flags = 0 ^ 0
        flags = flags | (FLAGS_ACK)
        payload = self.unacked_data[:MSS]

        client_addr, client_port, server_addr, server_port = self.id_conexao
        pass_2_handshake_header = make_header(server_port, client_port, self.seq_no, self.ack_no, flags)
        pass_2_handshake_header = fix_checksum(pass_2_handshake_header + payload, server_addr, client_addr)
        self.servidor.rede.enviar(pass_2_handshake_header, client_addr)
        self._start_timer()

    def registrar_recebedor(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que dados forem corretamente recebidos
        """
        self.callback = callback

    def fechar(self):
        if self.fin_ack:
            del self.servidor.conexoes[self.id_conexao]

        else:
            payload = b''
            self.callback(self, payload)
            self._send_flag(FLAGS_FIN)
            self.fin_ack = True
            self.seq_no += 1

    def enviar(self, dados):
        """
        Usado pela camada de aplicação para enviar dados
        """
        # TODO: implemente aqui o envio de dados.
        # Chame self.servidor.rede.enviar(segmento, dest_addr) para enviar o segmento
        # que você construir para a camada de rede.
        if dados != None:
            self.unsent_data += dados

        src_addr, src_port, dst_addr, dst_port = self.id_conexao
        self.increase_window_size = len(self.unsent_data[:self.window_size * MSS]) / MSS >= self.window_size
        self.next = self.seq_no
        for i in range(self.window_size):
            segmento = self.unsent_data[:MSS]
            if len(segmento) > 0:
                self.unsent_data = self.unsent_data[MSS:]
                self.unacked_data += segmento
                header = make_header(dst_port, src_port, self.next, self.ack_no, FLAGS_ACK)
                self.servidor.rede.enviar(fix_checksum(header + segmento, dst_addr, src_addr), src_addr)
                self.next += len(segmento)
        self.T0 = time()
        self._start_timer()