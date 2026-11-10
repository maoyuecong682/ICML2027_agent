无监督训练+system information

### 1.unsupervised learning 文章架构

## agent anomaly score

定义了一个无监督方式训练的detection model

## hierarchical agent encoder
由agent node feature construction和hierachical graph encoding两部分组成。纳入考虑ego neighbour 和global三个变量。

# agent node feature construction
sentenceBERT函数，溯源到Nils Reimers and Iryna Gurevych。2019. Sentence-bert:
Sentence embeddings using siamese bert-networks.arXiv preprint arXiv:1908.10084

# hierachical graph encoding
纳入考虑ego neighbour 和global三个变量。使用MLP融合。

## corruption-guided attack detector

BERT＋为agent添加随机扰动


### 2.实验细节
关注四个问题:
## RQ1 & RQ2 
baseline：G-safeguard，DOMINANT，PREM，TAM
supervised & unsupervised 
LLM: Qwen3-30B-A3B (Yang et al., 2025), Deepseek-v3 (Liu et al., 2024) and commercial LLMs (GPT-4o-mini)as agent back-bones
topology:random tree tar chain
观测的指标是：AUC ASR
## RQ3 larger MAS (3个 20个 50个)
## RQ4 contributions
在于整合ego neighbour global三个part的信息。

