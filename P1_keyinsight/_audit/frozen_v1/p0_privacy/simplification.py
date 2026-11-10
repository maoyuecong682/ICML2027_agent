"""Optional, independently switchable transformations of constructed privacy graphs.

No LLM calls. Originals remain immutable; every contraction has a source map.
Task text is context, never evidence that a recipient received its contents.
"""
import argparse
import copy
import hashlib
import itertools
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SimplificationConfig:
    enabled: bool = False
    entity_dedup: bool = True
    hide_empty: bool = True
    group_lists: bool = True
    remove_graphiti_system: bool = True
    remove_graphiti_relations: bool = True


def simplify_graph(original, config):
    """Contract actual topology; retain provenance and list membership as attributes."""
    graph = copy.deepcopy(original)
    if not config.enabled:
        return graph
    nodes = {n['id']: n for n in graph['nodes']}
    mapping = {nid: nid for nid in nodes}
    removed = {}
    operations = []

    def root(nid):
        while mapping[nid] != nid:
            nid = mapping[nid]
        return nid

    def contract(source, target, reason):
        source, target = root(source), root(target)
        if source == target:
            return
        if nodes[source].get('receiver_id') != nodes[target].get('receiver_id'):
            raise ValueError('Cannot merge different recipients')
        mapping[source] = target
        nodes[target].setdefault('absorbed_records', []).append(copy.deepcopy(nodes[source]))
        operations.append({'operation': reason, 'source': source, 'target': target})

    if config.entity_dedup:
        # Align only evidenced representations, not arbitrary same-name entities.
        for e in graph['edges']:
            if e['kind'] == 'lexical_entity_alignment':
                contract(e['source'], e['target'], 'graphiti_entity_first')
        for n in list(nodes.values()):
            if (n['type'] == 'normalized_received_fact' and
                    n.get('extraction_method') == 'exact_parameter' and '\n' in n['label']):
                requests = [q for q in nodes.values() if q['type'] == 'actual_disclosure'
                            and q['disclosure_id'] == n.get('receipt_id')]
                if len(requests) == 1:
                    contract(n['id'], requests[0]['id'], 'full_parameter_already_in_request_attributes')
        for atom in list(nodes.values()):
            if atom['type'] != 'disclosed_atom':
                continue
            candidates = []
            for fact in nodes.values():
                if fact['type'] != 'normalized_received_fact' or fact['label'] != atom['label']:
                    continue
                if fact.get('receipt_id') == atom.get('disclosure_id'):
                    candidates.append(root(fact['id']))
            candidates = list(dict.fromkeys(candidates))
            if len(candidates) == 1:
                contract(atom['id'], candidates[0], 'same_received_value')
        # Remaining exact duplicates must share receipt, parameter path and span.
        seen = {}
        for atom in list(nodes.values()):
            if atom['type'] != 'disclosed_atom' or root(atom['id']) != atom['id']:
                continue
            a = atom['annotation']
            key = (atom['receiver_id'], atom['disclosure_id'], a['parameter_path'],
                   a['span_start'], a['span_end'], atom['label'])
            if key in seen:
                contract(atom['id'], seen[key], 'same_received_span')
            else:
                seen[key] = atom['id']
        checks = []
        for n in original['nodes']:
            if n['type'] == 'disclosed_atom':
                checks.append({'source_id': n['id'], 'canonical_id': root(n['id']),
                               'in_task_prompt': n['label'] in graph['task']['prompt'],
                               'source': 'observed_request_annotation',
                               'supplement': nodes[root(n['id'])]['type'] != 'graphiti_entity'})
        graph.setdefault('simplification', {})['task_text_checks'] = checks

    if config.hide_empty:
        for n in nodes.values():
            if n['type'] == 'actual_disclosure' and n.get('empty_parameters'):
                removed[n['id']] = 'empty_request'
    if config.remove_graphiti_system:
        for n in nodes.values():
            if n['type'] == 'graphiti_episode':
                removed[n['id']] = 'graphiti_system_episode'

    if config.group_lists:
        # Group by actual list subject, receiving request and predicate; never
        # group unrelated objects merely because their names look similar.
        groups = {}
        for n in original['nodes']:
            if n['type'] == 'normalized_received_fact' and n['claim']['predicate'].endswith('.item'):
                key = (n['receiver_id'], n['receipt_id'], n['claim']['subject'], n['claim']['predicate'])
                groups.setdefault(key, []).append(n)
        for key, members in groups.items():
            if len(members) < 2:
                continue
            nid = 'list:' + hashlib.sha256(repr(key).encode()).hexdigest()[:16]
            nodes[nid] = {'id': nid, 'type': 'representative_object',
                          'label': '行李物品集合' if key[3] == 'packing.item' else '同类清单集合',
                          'receiver_id': key[0], 'receipt_id': key[1],
                          'members': [n['label'] for n in members], 'member_count': len(members),
                          'aggregation': 'collection_not_single_item',
                          'evidence': [copy.deepcopy(n['evidence']) for n in members]}
            mapping[nid] = nid
            # Merge every evidenced representation even if entity dedup is off.
            ids = {n['id'] for n in members}
            for e in original['edges']:
                if e['kind'] == 'lexical_entity_alignment' and e['source'] in ids:
                    ids.add(e['target'])
            for n in original['nodes']:
                if n['type'] == 'disclosed_atom' and n.get('disclosure_id') == key[1]:
                    if any(n['label'] == m['label'] for m in members):
                        ids.add(n['id'])
            for source in sorted(ids):
                contract(source, nid, 'same_list_members')
            # Parallel LISTS_ITEM declarations become one collection relation;
            # each original declaration and quote remains in absorbed_records.
            claims = []
            for n in original['nodes']:
                if n['type'] != 'graphiti_relation_claim' or n.get('predicate') != 'LISTS_ITEM':
                    continue
                objects = [e['target'] for e in original['edges']
                           if e['source'] == n['id'] and e['kind'] == 'semantic_object']
                if objects and root(objects[0]) == nid:
                    subjects = tuple(sorted(e['source'] for e in original['edges']
                                            if e['target'] == n['id'] and e['kind'] == 'semantic_subject'))
                    claims.append((subjects, n['id']))
            heads = {}
            for subject, cid in claims:
                if subject in heads:
                    contract(cid, heads[subject], 'parallel_list_relations')
                else:
                    heads[subject] = cid
                    nodes[cid]['label'] = '文件列有行李物品集合（成员见集合属性）'
                    nodes[cid]['predicate'] = 'LISTS_COLLECTION'

    if config.remove_graphiti_relations:
        for n in nodes.values():
            if n['type'] == 'graphiti_relation_claim':
                removed[n['id']] = 'graphiti_semantic_relation_layer'

    final_ids = {root(nid) for nid in nodes if nid not in removed}
    final_ids.difference_update(removed)
    edges, seen_edges = [], {}
    for e in original['edges']:
        source, target = root(e['source']), root(e['target'])
        if source not in final_ids or target not in final_ids or source == target:
            continue
        key = (source, target, e['kind'], e.get('slot'), e.get('template_slot'))
        if key in seen_edges:
            seen_edges[key].setdefault('absorbed_edges', []).append(copy.deepcopy(e))
            continue
        value = {**copy.deepcopy(e), 'source': source, 'target': target}
        value['id'] = 'simplified_edge:' + str(len(edges))
        seen_edges[key] = value
        edges.append(value)
    graph['nodes'] = [n for nid, n in nodes.items() if nid in final_ids]
    graph['edges'] = edges
    # References in factors and snapshots must point to the contracted topology.
    def remap(value):
        if isinstance(value, str):
            return root(value) if value in mapping and value not in removed else value
        if isinstance(value, list):
            result = [remap(v) for v in value]
            return list(dict.fromkeys(result)) if all(isinstance(v, str) for v in result) else result
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value
    for n in graph['nodes']:
        if 'support' in n:
            n['support'] = remap(n['support'])
    graph['joint_factors'] = remap(graph['joint_factors'])
    graph['simplification'].update({
        'applied': True, 'config': asdict(config), 'operations': operations,
        'node_map': {nid: (None if nid in removed else root(nid)) for nid in mapping},
        'removed_records': [dict(record=copy.deepcopy(nodes[nid]), reason=reason)
                            for nid, reason in removed.items()],
        'before': {'nodes': len(original['nodes']), 'edges': len(original['edges'])},
        'after': {'nodes': len(graph['nodes']), 'edges': len(edges)},
        'disclosure_effect': 'structural_only_members_and_evidence_retained_not_measured_privacy_reduction',
    })
    graph['statistics'].update(nodes=len(graph['nodes']), edges=len(edges),
                               node_types=dict(Counter(n['type'] for n in graph['nodes'])))
    graph['construction_validation'] = graph.pop('validation', None)
    validate_simplified(original, graph)
    graph['validation'] = copy.deepcopy(graph['simplification']['validation'])
    return graph


def validate_simplified(original, graph):
    nodes = {n['id']: n for n in graph['nodes']}
    if len(nodes) != len(graph['nodes']):
        raise ValueError('Duplicate simplified node')
    for e in graph['edges']:
        a, b = nodes[e['source']], nodes[e['target']]
        if a.get('receiver_id') and b.get('receiver_id') and a['receiver_id'] != b['receiver_id']:
            raise ValueError('Cross-recipient contraction')
    for factor in graph['joint_factors']:
        previous = next(f for f in original['joint_factors'] if f['factor_node'] == factor['factor_node'])
        if (factor['status'], factor['missing_slots']) != (previous['status'], previous['missing_slots']):
            raise ValueError('Simplification changed inference status')
        for ids in factor['support'].values():
            if any(nid not in nodes for nid in ids):
                raise ValueError('Lost factor support')
    for n in original['nodes']:
        if n['type'] == 'explicit_and_factor':
            before = [e.get('slot') for e in original['edges'] if e['target'] == n['id'] and e['kind'] == 'and_premise']
            after = [e.get('slot') for e in graph['edges'] if e['target'] == n['id'] and e['kind'] == 'and_premise']
            if sorted(before) != sorted(after):
                raise ValueError('Lost explicit AND premise')
    graph['simplification']['validation'] = {'passed': True, 'checks': [
        'edge_endpoints', 'receiver_isolation', 'factor_support', 'inference_status', 'explicit_AND_slots']}


def terminal(graph):
    """Render the transformed graph, never the untransformed native sidecar."""
    if not graph.get('simplification', {}).get('applied'):
        from .task_graph import graph_terminal
        return graph_terminal(graph)
    nodes = {n['id']: n for n in graph['nodes']}
    edges = graph['edges']
    def label(nid):
        n = nodes[nid]
        value = n['label'].replace('\n', ' / ')
        return value if len(value) < 110 else '完整请求正文（原文保存在节点属性）'
    lines = [f"┌─ {graph['task']['task_key']}  简化开关配置：" +
             ', '.join(f'{k}={int(v)}' for k, v in graph['simplification']['config'].items()),
             f"│  {graph['simplification']['before']} → {graph['simplification']['after']}"]
    for r in (n for n in nodes.values() if n['type'] == 'business_receiver'):
        lines.append('├─ 接收者：' + r['label'])
        for q in (n for n in nodes.values() if n['type'] == 'actual_disclosure' and n['receiver_id'] == r['receiver_id']):
            lines.append(f"│  ├─ {q['event_id']} {q['label']} ──请求送达──> 接收者")
            facts = list(dict.fromkeys(e['target'] for e in edges if e['source'] == q['id']
                                      and e['kind'] in {'contains_atom', 'normalized_fact'}))
            for nid in facts:
                annotations = [e for e in edges if e['source'] == nid and e['kind'] in {'direct_label', 'indirect_label'}]
                suffix = '; '.join(('候选关联：' if e['kind'] == 'indirect_label' else '字段：') + label(e['target']) for e in annotations)
                lines.append('│  │  ├─ [' + label(nid) + ']' + ('  ' + suffix if suffix else ''))
                if nodes[nid]['type'] == 'representative_object':
                    lines.append('│  │  │  成员属性：' + '、'.join(nodes[nid]['members']))
            if q.get('empty_parameters'):
                lines.append('│  │  └─ {}')
    if graph['simplification']['config'].get('remove_graphiti_relations'):
        lines.append('├─ Graphiti 语义关系层已移出；实体保留')
    else:
        lines.append('├─ Graphiti 语义关系（关系声明节点以带标签的箭头展示）')
    for claim in (n for n in nodes.values() if n['type'] == 'graphiti_relation_claim'):
        subjects = [e['source'] for e in edges if e['target'] == claim['id'] and e['kind'] == 'semantic_subject']
        objects = [e['target'] for e in edges if e['source'] == claim['id'] and e['kind'] == 'semantic_object']
        for a, b in itertools.product(subjects, objects):
            lines.append(f"│  ├─ [{label(a)}] ──{claim['predicate']}──> [{label(b)}]")
    lines.append('├─ 联合依赖（保留原有验证状态）')
    for n in nodes.values():
        if n['type'] == 'explicit_and_factor':
            inputs = [label(e['source']) for e in edges if e['target'] == n['id'] and e['kind'] == 'and_premise']
            lines.append('│  ├─ AND(' + ' ∧ '.join(inputs) + ') → 文档明示的个人旅行计划【不证明实际出行】')
    for f in graph['joint_factors']:
        parts = []
        slot_names = {'query': '查询词', 'sender': '发件人', 'service': '服务名',
                      'email': '邮箱/个人标识', 'traveler_name': '姓名',
                      'destination': '目的地', 'dates': '日期', 'packing_items': '行李物品'}
        for slot in f['required_slots']:
            values = [label(nid) for nid in f['support'].get(slot, [])]
            name = slot.split(':')[-1]
            parts.append(slot_names.get(name, name) + ':' + (' / '.join(values) if values else '缺失'))
        status = '未激活' if f['missing_slots'] else '待验证'
        lines.append('│  ├─ AND(' + ' ∧ '.join(parts) + ') -?-> ' + label(f['output_node']) + '【' + status + '】')
    counts = Counter(n['type'] for n in nodes.values())
    lines.append('└─ 审计/历史保留：' + str({k: v for k, v in counts.items() if k in {
        'receiver_memory_state', 'audit_provenance_source', 'graphiti_episode'}}) +
        '；原文与溯源见 JSON 属性；结构压缩不宣称隐私信息减少。')
    return '\n'.join(lines)


def export_bundle(bundle, config, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 'p0.privacy.simplification.bundle.v1',
              'source_schema': bundle['schema_version'], 'config': asdict(config),
              'graphs': {k: simplify_graph(g, config) for k, g in bundle['graphs'].items()}}
    path = output_dir / '简化隐私图.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    drawings = [terminal(g) for g in result['graphs'].values()]
    (output_dir / '简化隐私图.md').write_text('\n\n'.join('```text\n' + s + '\n```' for s in drawings), encoding='utf-8')
    for drawing in drawings:
        print(drawing, flush=True)
    return result


def add_arguments(parser):
    parser.add_argument('--simplify', action=argparse.BooleanOptionalAction, default=False,
                        help='Master switch for post-construction simplification')
    for name in ('entity-dedup', 'hide-empty', 'group-lists', 'remove-graphiti-system',
                 'remove-graphiti-relations'):
        parser.add_argument('--' + name, action=argparse.BooleanOptionalAction, default=True)


def config_from_args(args):
    return SimplificationConfig(args.simplify, args.entity_dedup, args.hide_empty,
                                args.group_lists, args.remove_graphiti_system,
                                args.remove_graphiti_relations)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    folder = Path(__file__).resolve().parents[1] / 'outputs/graphiti_privacy'
    parser.add_argument('--input', type=Path, default=folder / '任务隐私图.json')
    parser.add_argument('--output-dir', type=Path, default=folder)
    add_arguments(parser)
    args = parser.parse_args(argv)
    original = args.input.read_bytes()
    bundle = json.loads(original)
    result = export_bundle(bundle, config_from_args(args), args.output_dir)
    if args.input.read_bytes() != original:
        raise ValueError('Original graph modified')
    return result


if __name__ == '__main__':
    main()
