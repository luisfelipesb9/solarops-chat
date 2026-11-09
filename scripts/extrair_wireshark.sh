#!/usr/bin/env bash
# Extrai do pcap as evidências textuais usadas no relatório (seção 6b).
set -euo pipefail
cd "$(dirname "$0")/.."
PCAP=evidencias/captura_5050_5051.pcap
OUT=evidencias

s_claro=$(tshark -r "$PCAP" -Y 'tcp.port==5050 && frame contains "teste wireshark 123"' -T fields -e tcp.stream | head -1)
{
  echo "$ tshark -r captura_5050_5051.pcap -q -z follow,tcp,ascii,$s_claro | grep wireshark"
  tshark -r "$PCAP" -q -z "follow,tcp,ascii,$s_claro" | grep -E "Node|wireshark" | cut -c1-200
} > "$OUT/wireshark_claro.txt"

s_tls=$(tshark -r "$PCAP" -Y 'tcp.port==5051 && tls.handshake.type==1' -T fields -e tcp.stream | head -1)
{
  echo "$ tshark -r captura_5050_5051.pcap -Y 'tcp.stream==$s_tls && tls'"
  tshark -r "$PCAP" -Y "tcp.stream==$s_tls && tls" | head -12 | sed -E 's/^ +//; s/(, Application Data){2,}.*$/, Application Data (x4)/'
  f=$(tshark -r "$PCAP" -Y "tcp.stream==$s_tls && tls.app_data" -T fields -e frame.number | sed -n 5p)
  echo "$ tshark -r captura_5050_5051.pcap -Y 'frame.number==$f' -T fields -e tls.app_data"
  tshark -r "$PCAP" -Y "frame.number==$f" -T fields -e tls.app_data | cut -c1-96
} > "$OUT/wireshark_tls.txt"

count() { tshark -r "$PCAP" -Y "$1" | wc -l | tr -d ' '; }
{
  echo "pacotes da porta 5050 contendo 'teste wireshark 123': $(count 'tcp.port==5050 && frame contains "teste wireshark 123"')"
  echo "pacotes da porta 5051 contendo 'teste wireshark 123': $(count 'tcp.port==5051 && frame contains "teste wireshark 123"')"
  echo "pacotes da porta 5051 contendo 'teste wireshark 456': $(count 'tcp.port==5051 && frame contains "teste wireshark 456"')"
  echo "pacotes da porta 5050 contendo 'teste wireshark 456': $(count 'tcp.port==5050 && frame contains "teste wireshark 456"')"
  echo "versão TLS negociada (Server Hello): $(tshark -r "$PCAP" -Y "tcp.stream==$s_tls && tls.handshake.type==2" -T fields -e tls.handshake.extensions.supported_version | head -1)"
} > "$OUT/wireshark_busca.txt"

cat "$OUT/wireshark_claro.txt" "$OUT/wireshark_tls.txt" "$OUT/wireshark_busca.txt"
