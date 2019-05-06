import torch
import torch.nn as nn
import torch.nn.functional as F
from model.utils import SOS_INDEX, EOS_INDEX
from model.attention import get_attention
from model.multi_layer_rnn_cell import MultiLayerLSTMCell, MultiLayerGRUCell

class Decoder(nn.Module):

    def __init__(self, embedding, hidden_size, rnn_type='LSTM', num_layers=1, attention_type='Bilinear', dropout=0):
        super(Decoder, self).__init__()
        self.embedding = embedding
        self.hidden_size = hidden_size
        self.rnn_type = rnn_type
        self.num_layers = num_layers
        self.dropout = dropout
        self.embed_size = embedding.embedding_dim
        if rnn_type == 'LSTM':
            self.rnn_cell = MultiLayerLSTMCell(
                input_size=self.embed_size * 2,
                hidden_size=hidden_size,
                num_layers=num_layers,
                dropout=dropout
            )
        else:
            self.rnn_cell = MultiLayerGRUCell(
                input_size=self.embed_size * 2,
                hidden_size=hidden_size,
                num_layers=num_layers,
                dropout=dropout
            )
        self.query_projection = nn.Linear(hidden_size, hidden_size)
        self.attention = get_attention(hidden_size, hidden_size, attention_type)
        self.output_projection = nn.Sequential(
            nn.Linear(2 * hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, self.embed_size)
        )

    def forward(self, src_memory, src_mask, init_states, init_output, trg):
        """
        :param src_memory: FloatTensor (batch_size, src_time_step, hidden_size)
        :param src_mask: ByteTensor (batch_size, src_time_step)
        :param init_states: (hidden, cell) or hidden
            hidden: FloatTensor (num_layers, batch_size, hidden_size)
            cell: FloatTensor (num_layers, batch_size, hidden_size)
        :param init_output: FloatTensor (batch_size, embed_size)
        :param trg: LongTensor (batch_size, trg_time_step)
        :return:
        """
        batch_size, max_len = trg.size()
        states = init_states
        output = init_output
        logits = []
        for i in range(max_len):
            token = trg[:, i]
            logit, states, output = self.step(src_memory, src_mask, token, states, output)
            logits.append(logit)
        logits = torch.stack(logits, dim=1)
        return logits

    def step(self, src_memory, src_mask, token, prev_states, prev_output):
        """
        :param src_memory: FloatTensor (batch_size, src_time_step, hidden_size)
        :param src_mask: ByteTensor (batch_size, src_time_step)
        :param token: LongTensor (batch_size,)
        :param prev_states: (hidden, cell) or hidden
            hidden: FloatTensor (num_layers, batch_size, hidden_size)
            cell: FloatTensor (num_layers, batch_size, hidden_size)
        :param prev_output: (batch_size, embed_size)
        :return:
        """
        token_embedding = self.embedding(token)
        rnn_input = torch.cat([token_embedding, prev_output], dim=1)
        states = self.rnn_cell(rnn_input, prev_states)
        if self.rnn_type == 'LSTM':   # LSTM
            top_hidden = states[0][-1]
        else:   # GRU
            top_hidden = states[-1]
        query = self.query_projection(top_hidden)
        context = self.attention(query, src_memory, src_memory, src_mask)
        output = self.output_projection(torch.cat([top_hidden, context], dim=1))
        logit = torch.mm(output, self.embedding.weight.t())
        return logit, states, output

    def get_init_output(self, src_memory, src_lens, init_states):
        """
        :param src_memory: FloatTensor (batch_size, src_time_step, hidden_size)
        :param src_lens: LongTensor (batch_size,)
        :param init_states: (hidden, cell) or hidden
            hidden: FloatTensor (num_layers, batch_size, hidden_size)
            cell: FloatTensor (num_layers, batch_size, hidden_size)
        :return init_output: FloatTensor (batch_size, embed_size)
        """
        if self.rnn_type == 'LSTM':  # LSTM
            init_top_hidden = init_states[0][-1]
        else:   # GRU
            init_top_hidden = init_states[-1]
        src_mean = src_memory.sum(dim=1, keepdim=False) / src_lens.unsqueeze(-1).float()
        init_output = self.output_projection(torch.cat([init_top_hidden, src_mean], dim=1))
        return init_output