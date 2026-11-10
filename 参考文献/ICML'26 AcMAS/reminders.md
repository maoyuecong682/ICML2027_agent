When Agents Go Rogue

### activation-based framework
三个基础的定义，在后续板块使用，分别是激活向量、激活相关性和激活的传播原则。
## activation vectors
extract layer-wise hidden states into a compact feature vector;
输入：input 
规定same LLM backbones（相同的大模型的背景）;same dimension d（用来表示智能体的向量本身的维度）

## activation correlation
计算两个智能体之间激活向量的相关程度

## activation propagation in MAS
智能体的激活向量会随着新的输入和来自上游的智能体的信息而迭代

### detection
计算和normal(认为是benign的智能体的表现指标)的方向差异程度。
首先定义了normal值的计算，其次是确定了divergence的定义和计算方式；

for asynchronous MAS
针对异步执行的MAS本身来说，task来决定本轮究竟会用到哪一个agent，而不是每一轮都激活所有的agent。这样的形式更加灵活。我们的normal参数的计算是固定的，因为存在这样的结论：高层次的推理范式不会根据不同的task和执行阶段和上下文改变。


# adapative correction via activation steering
我们获取了μnormal之后就可以将agent向量朝着更加正常的方向调整。
是根据我们定义的调整参数去调整，lambdai，而他的输入是agent divergence magnitude。