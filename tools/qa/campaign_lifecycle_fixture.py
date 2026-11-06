"""Twelve physical rounds, ten stages, one clock gap; QA values are estimates."""
import copy
from tools.qa.campaign_plan_fixture import inputs as base_inputs
from gentactix import historical_operations, missions

NOTE='单世界生命周期软件QA；阶段、时长、部署和资源均为估计，不是完整万家岭史实。'


def inputs():
    source,p=base_inputs();example=copy.deepcopy(p['campaign_plan']['nodes'][2]);nodes=[];phases=[]
    for number in range(10):
        identity='phase'+str(number+1)
        goals=[]
        if number!=3:
            node=copy.deepcopy(example);node.update(id='milestone'+str(number+1),label='QA阶段'+str(number+1)+'兵力保持',
                after={'mode':'all','node_ids':[]},latch=True,operation_ids=[],assumption=NOTE)
            nodes.append(node);goals=[node['id']]
        phases.append(dict(id=identity,label='QA阶段'+str(number+1),goal_ids=goals,
            minimum_duration_seconds=5400 if number==3 else 0,operation_ids=[],assumption=NOTE))
    nodes.append(copy.deepcopy(p['campaign_plan']['nodes'][3]))
    p['campaign_plan']['nodes']=nodes
    p['campaign_plan']['outcomes']['red']['node_ids']=[nodes[-2]['id']]
    p['campaign_plan']['elimination_ends']=False
    p['campaign_lifecycle']=dict(version='campaign-lifecycle-1',phases=phases,finish_policy='all_phases',assumption=NOTE)
    return source,p


def world():return historical_operations.initial(*inputs())


def session():
    return dict(id='lifecycle-qa',turn_count=0,role_epoch=0,product_mode='historical',simulation_mode='open',
        execution_backend='narrative',time_step='30分钟',war_state=world())
