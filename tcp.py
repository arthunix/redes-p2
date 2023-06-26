import asyncio
import random
from time import time
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
            # Ignora segmentos que não são destinados à porta do nosso servidor
            return
        if not self.rede.ignore_checksum and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('descartando segmento com checksum incorreto')
            return

        payload = segment[4*(flags>>12):]
        id_conexao = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            # A flag SYN estar setada significa que é um cliente tentando estabelecer uma conexão nova
            # TODO: talvez você precise passar mais coisas para o construtor de conexão
            conexao = self.conexoes[id_conexao] = Conexao(self, id_conexao)

            # TODO: você precisa fazer o handshake aceitando a conexão. Escolha se você acha melhor
            # fazer aqui mesmo ou dentro da classe Conexao.

            # STEP 1
            flags = flags ^ flags
            flags = flags | (FLAGS_SYN | FLAGS_ACK)

            conexao.seq_no = random.randint(0, 0xffff)
            conexao.ack_no = seq_no + 1

            server_port, client_port, server_addr, client_addr = dst_port, src_port, dst_addr, src_addr 

            pass_2_handshake_header = make_header(server_port, client_port, conexao.seq_no, conexao.ack_no, flags)
            pass_2_handshake_header = fix_checksum(pass_2_handshake_header, server_addr, client_addr)
            self.rede.enviar(pass_2_handshake_header, client_addr)

            conexao.seq_no += 1
            # STEP 1

            if self.callback:
                self.callback(conexao)
        elif id_conexao in self.conexoes:
            # Passa para a conexão adequada se ela já estiver estabelecida
            self.conexoes[id_conexao]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))


class Conexao:
    def __init__(self, servidor, id_conexao):
        self.servidor = servidor
        self.id_conexao = id_conexao
        self.callback = None
        self.seq_no = None
        self.ack_no = None
        self.timer = None
        self.timeoutInterval = 1
        self.pacotes_sem_ack = []
        # self.timer = asyncio.get_event_loop().call_later(1, self._exemplo_timer)  # um timer pode ser criado assim; esta linha é só um exemplo e pode ser removida
        # self.timer.cancel()   # é possível cancelar o timer chamando esse método; esta linha é só um exemplo e pode ser removida
        
    def _exemplo_timer(self):
        # Esta função é só um exemplo e pode ser removida
        print('Este é um exemplo de como fazer um timer')

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        # TODO: trate aqui o recebimento de segmentos provenientes da camada de rede.
        # Chame self.callback(self, dados) para passar dados para a camada de aplicação após
        # garantir que eles não sejam duplicados e que tenham sido recebidos em ordem.
        print('recebido payload: %r' % payload)

        # STEP 2
        # In this case it is not the packet we expecting, exactly the next
        if len(payload) <= 0 or (seq_no != self.ack_no):
            return
        self.callback(self, payload)
        self.ack_no += len(payload) # maybe I will need to modify seq value in function send

        dst_addr, dst_port, src_addr, src_port = self.id_conexao

        pass_2_handshake_header = make_header(src_port, dst_port, self.seq_no, self.ack_no, FLAGS_ACK)
        pass_2_handshake_header = fix_checksum(pass_2_handshake_header, src_addr, dst_addr)
        self.servidor.rede.enviar(pass_2_handshake_header, dst_addr)
        # STEP 2

    def registrar_recebedor(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que dados forem corretamente recebidos
        """
        self.callback = callback

    #STEP 3
    def _timer(self):
        if self.pacotes_sem_ack:
            envio, _, dst_addr, _ = self.pacotes_sem_ack[0]
            self.servidor.rede.enviar(envio, dst_addr)
            self.pacotes_sem_ack[0][3] = None
            
    def enviar(self, dados):
        """
        Usado pela camada de aplicação para enviar dados
        """
        # TODO: implemente aqui o envio de dados.
        # Chame self.servidor.rede.enviar(segmento, dest_addr) para enviar o segmento
        # que você construir para a camada de rede.
   
        dst_addr, dst_port, src_addr, src_port = self.id_conexao

        flags = 0 | FLAGS_ACK

        for i in range(int(len(dados)/MSS)):
            ini = i*MSS
            fim = min(len(dados), (i+1)*MSS)

            payload = dados[ini:fim]

            envio = make_header(src_port, dst_port, self.seq_no, self.ack_no, flags)
            envio_checksum_ok = fix_checksum(envio+payload, src_addr, dst_addr)
            self.servidor.rede.enviar(envio_checksum_ok, dst_addr)

            self.timer = asyncio.get_event_loop().call_later(self.timeoutInterval, self._timer)
            self.pacotes_sem_ack.append( [envio_checksum_ok, len(payload), dst_addr, round(time(), 5)] )

            self.seq_no += len(payload)
    #STEP 3
    
    def fechar(self):
        """
        Usado pela camada de aplicação para fechar a conexão
        """
        # TODO: implemente aqui o fechamento de conexão
        pass
