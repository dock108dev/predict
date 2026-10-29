"""Lossless shared JSON trees with bounded expansion and backward-only references.

The encoding preserves types, original strings and every input. It changes no
financial identity. Decode returns independent mutable containers.
"""
import json
from .store import encoded

VERSION = 'shared-json-1'
MAX_EXPANDED = 96 * 1024 * 1024
MAX_NODES = 1000000


def _visit(v,nodes,indexes):
    if isinstance(v,dict):node=['o',[[k,_visit(x,nodes,indexes)] for k,x in v.items()]]
    elif isinstance(v,list):node=['a',[_visit(x,nodes,indexes) for x in v]]
    else:node=['v',v]
    key=encoded(node)
    if key in indexes:return indexes[key]
    i=len(nodes);indexes[key]=i;nodes.append(node)
    if len(nodes)>MAX_NODES:raise ValueError('shared_json_node_capacity')
    return i


def pack(value):
    nodes=[]
    root=_visit(value,nodes,{})
    return dict(encoding=VERSION,nodes=nodes,root=root)


def _restore(i,nodes):
    kind,body=nodes[i]
    return {k:_restore(r,nodes) for k,r in body} if kind=='o' else [_restore(r,nodes) for r in body] if kind=='a' else body


def unpack(value, *, guard=None, fields=None):
    if value.get('encoding')!=VERSION:
        return value if fields is None else {k:value[k] for k in fields}
    nodes=value['nodes'];sizes=[];depths=[];allocations=[]
    if not isinstance(nodes,list) or len(nodes)>MAX_NODES:raise ValueError('shared_json_node_capacity')
    for i,node in enumerate(nodes):
        kind,body=node
        refs=body if kind=='a' else [x[1] for x in body] if kind=='o' else []
        if any(type(r) is not int or not 0<=r<i for r in refs):raise ValueError('shared_json_reference_invalid')
        if kind=='v':
            if isinstance(body,(list,dict)):raise ValueError('shared_json_scalar_invalid')
            size=len(encoded(body));depth=0;allocation=0
        elif kind in ('o','a'):
            if kind=='o' and (any(not isinstance(k,str) for k,_ in body) or len({k for k,_ in body})!=len(body)):
                raise ValueError('shared_json_keys_invalid')
            size=2+sum(sizes[r]+1 for r in refs)+(sum(len(encoded(k))+1 for k,_ in body) if kind=='o' else 0)
            depth=1+max((depths[r] for r in refs),default=0)
            # Scalars/keys already belong to the parsed tree and _restore reuses
            # them. Only containers are duplicated. Budget generous per-entry
            # container overhead instead of repeatedly charging long strings.
            allocation=sum(allocations[r] for r in refs)+(256+64*len(refs) if kind=='o' else 64+16*len(refs))
        else:raise ValueError('shared_json_type_invalid')
        if size>MAX_EXPANDED or depth>96:raise ValueError('shared_json_expansion_capacity')
        sizes.append(size);depths.append(depth);allocations.append(allocation)
    root=value['root']
    if type(root) is not int or not 0<=root<len(nodes):raise ValueError('shared_json_root_invalid')
    if fields is None:
        if guard:guard(allocations[root])
        return _restore(root,nodes)
    # Validate the entire encoded tree above, but materialize only the requested
    # top-level evidence. Selected reads need either observed or financial inputs,
    # not two independently mutable copies of both complete game bundles.
    kind,body=nodes[root]
    if kind!='o':raise ValueError('shared_json_object_required')
    refs=dict(body)
    selected={k:refs[k] for k in fields}
    if guard:guard(256+64*len(selected)+sum(allocations[r] for r in selected.values()))
    return {k:_restore(r,nodes) for k,r in selected.items()}


def dumps(value):
    return encoded(pack(value)).decode()


def loads(text, *, guard=None, fields=None):
    return unpack(json.loads(text),guard=guard,fields=fields)


def compact_board(board):
    # Coverage projects Odds fields directly in SQL. Preserve its existing
    # pooled wire contract; share larger financial evidence on EV/Arbs.
    if board.get('view')=='odds':return board
    if len(encoded(board))<=32*1024:return board
    fields=('prices','rows','price_field_pool','financial_field_pool','native_wordings')
    content={k:board[k] for k in fields if k in board}
    tree=pack(content)
    if len(encoded(tree))+64>=len(encoded(content)):return board
    for k in content:board.pop(k)
    board.update(prices=[],rows=[],shared_fields=tree)
    return board


def expand_board(board):
    tree=board.pop('shared_fields',None)
    if tree is not None:
        restored=unpack(tree)
        if set(restored)-{'prices','rows','price_field_pool','financial_field_pool','native_wordings'}:
            raise ValueError('shared_board_fields_invalid')
        board.update(restored)
    return board
