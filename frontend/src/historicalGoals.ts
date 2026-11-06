import type {HistoricalParameters,HistoricalScenarioBasis} from './types';

export function historicalCampaignGoalAllowed(p:Pick<HistoricalParameters,'campaign'|'campaign_scope'|'campaign_plan'|'goal'>,interaction?:HistoricalScenarioBasis['interaction']):boolean {
 if(!p.campaign)return true;
 if(interaction?.kind==='non_contact_transfer'){
  const team=p.goal.team??'red',other=team==='red'?'blue':'red';
  return !!p.campaign_scope&&!!p.campaign_plan&&p.goal.termination_mode==='objectives'&&
   interaction.active_teams.includes(team)&&['breakout','crossing'].includes(p.goal.profile)&&
   !p.campaign.objective_policy&&!p.campaign.surrender.enabled&&p.campaign.objective.relief_regions.length===0&&
   p.campaign_plan.outcomes[team].node_ids.length>0&&p.campaign_plan.outcomes[other].node_ids.length===0;
 }
 if(p.campaign_plan)return p.goal.termination_mode==='objectives'&&
  ['assault','delay'].includes(p.goal.profile)&&!p.campaign.objective_policy;
 return p.goal.profile==='assault'?!p.campaign.objective_policy:
  p.goal.profile==='delay'&&!!p.campaign_scope&&p.campaign.objective_policy==='defensive-delay-1';
}
