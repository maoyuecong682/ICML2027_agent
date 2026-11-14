"""Persist the tool observations actually delivered to each execution agent.

This is an observation ledger, not a replacement for messages_a/messages_b.
It never gives B the native responses seen only by A (or vice versa).
"""
import copy


def tool_observation(event):
    if event.get('type') != 'TOOL':
        return None
    payload = event['payload']
    agent = payload.get('target', event.get('actor'))
    if agent not in {'A', 'B'} or agent != event.get('actor'):
        raise ValueError('Tool response target must match the executing agent')
    error = payload.get('error')
    if 'delivered_content' in payload:
        content = payload['delivered_content']
        evidence = 'TOOL.payload.delivered_content'
    elif error is not None:
        content, evidence = f'ERROR: {error}', 'TOOL.payload.error'
    elif 'result' in payload:
        content, evidence = payload['result'], 'TOOL.payload.result'
    else:
        return None  # Missing evidence is not an empty successful response.
    if not isinstance(content, str):
        raise ValueError('Recorded delivered tool content must be a string')
    return {'event_id': event['id'], 'tool': payload['name'],
            'agent_id': agent, 'tool_call_id': payload.get('tool_call_id'),
            'observed_at': event.get('timestamp'), 'content': content,
            'error': copy.deepcopy(error), 'delivery_evidence': evidence,
            'direction': 'receiver_to_agent'}


def execution_memory_from_graph(graph):
    agents = {actor: {'agent_id': actor, 'tool_observations': [],
                      'received_agent_messages': []} for actor in ('A', 'B')}
    for event in graph['nodes']:
        observation = tool_observation(event)
        if observation is not None:
            agents[observation['agent_id']]['tool_observations'].append(observation)
        elif event.get('type') == 'MESSAGE':
            payload = event['payload']
            target = payload.get('target')
            if target in agents and isinstance(payload.get('content'), str):
                agents[target]['received_agent_messages'].append({
                    'event_id': event['id'], 'source': payload.get('source'),
                    'observed_at': event.get('timestamp'), 'content': payload['content']})
    return {'schema': 'execution.observation-memory.v1', 'agents': list(agents.values()),
            'scope': 'actual per-agent tool returns and delivered agent messages; not pooled'}
