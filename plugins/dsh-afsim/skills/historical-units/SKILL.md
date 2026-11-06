---
name: historical-unit-configuration
description: 从固定历史编制与阶段生成逐单位计算参数；保持真实ID与番号，不使用教学代表编组。
---

# 具名历史单位配置

若`required_models`含`live-footprint-density-1`，须在公共配置保留`fire_dynamics={version:"live-footprint-density-1",assumption:"明确估计依据"}`。它独立于`fire_accounting`；不修改既有库存、伤亡系数或历史初态。动态密度按同批现存人员、同根及当前坐标格共享，不代表区域重叠、溅射、历史标定或完整时间收敛。未选择时不升级旧规则。

若要求`live-footprint-density-2`，同一字段的version必须为该值，不能降为第一版。它保留动态密度，另启用`fixed-time-suppression-1`：原生压制跨轮携带精确余量，补足轮末未采样时段；不是全部机动、装备、保障时间收敛或历史效能认证。仍仅填写初态整数压制与估计依据，不生成运行时余量或原生回执。两种密度版本不可同时选择。

## 用户固定数值

`get_scenario_basis.fixed_parameters`列出用户通过表单明确固定的数值；它们是本次建模输入，不是历史事实。数值已在本片模板预填，必须保留；自然语言若要求另一数值，说明冲突，不修改固定值。宿主不会把错误模型输出悄悄改回正确值：工具返回`updated=false`及`fixed_parameter_conflicts`时，读取当前草稿，修正本片补丁后再提交，不能声称原补丁已保存。

公共片只看到公共固定项，单位片看到公共及其已分配单位的固定项；不得借此读取其他单位分片。预填不等于工具已经执行，各片仍须取得实际更新、最终验证及版本回执。固定项仅约束数值映射字段，不锁定说明文字；总说明和每单位依据须如实区分用户假设、史料事实与未知。未固定数值继续按来源与约束估计，不把自然语言数值自行升级成已锁定条件。

## 失败配置与显式修订

最终复核仍只读；初粮、容量或其他输入不通过时，不修改已锁定分片、不把失败回执说成成功，也不自动补足库存。已保存全部单位的失败配置可由用户在界面显式读取和修订，再通过既有完整校验另存新想定；原草稿、DSH会话及失败记录保留。这是人工修订原DSH参数，不是模型重新生成，不能把人工改值归因给DSH或将其称为史实。原固定输入、范围、引擎、时间步长和必需模型仍须遵守；改变这些原约束应明确重新生成。

## 会战编制与投入范围

运行中的临时指挥支持多级任务群；`parent_id`是当前作战配属，不改来源历史隶属。`members`只记录直属叶子，父级汇总和下令覆盖子群的唯一执行叶子；查询成员时查看`command_chain`，不能把各级统计相加。已配属叶子通过其临时指挥链下令；历史父节点只能向未临时配属的下级下令。组织调整不改变位置、人员、装备或库存，也不取消已确认的单位命令。

未选固定窗口的新累计会战配置使用`campaign-oob-deployment-2`；已选窗口保留模板中的`campaign-oob-window-1`，不能自行替换。逐个填写`campaign_scope.remainders`：未核余部只能声明`excluded_unquantified`并解释本次仅投入已列下级；只有来源中`children_coverage.status=complete`才允许`covered_by_children`。不能删除这些条目或把未知余部填零，不能称本次已覆盖整军。v1仅用于恢复旧冻结定义。

工具若返回`readonly_campaign_window`，它固定史料版本、起始阶段与模型日界。宿主保留完整窗口快照，公共参数patch省略`campaign_scope.window`，不回传全文或修改其摘要；保留`clock.start`和`campaign_scope.planning_end`所给边界。后者只约束初态到场计划，按目标结束时可以继续到窗外，不自动注入后续部队或历史结局。actor_index是本窗计算候选，不能换成全役累计名单；未知兵额、装备、阵位和到场仍逐项说明估计。

若还有`parameter_estimates`，这是未经历史标定的探索性先验，不是史料人数上下限。全局工作区和本片单位人员／装备／角色／自卫直射／初始位置范围须遵守；不可据最大值称满编，装备0仅指本模型不投入。显式填写时间保障和分类粮弹，粮秣工作量不是按人数或重量标定的口粮。`objectives`模板中的`campaign_plan`必须同时填写双方地域、最少人员、保持秒数、保存比例；不删除方向、改承担者、来源或依赖。若本次分为计算分队，目标中的父ID按所配parts顺序展开成`父ID::part_id`，不能父子同时计入。公共片会立即校验完整目标数值，不能把null留到单位片。到场时点另作估计，不按未来历史调令自动解锁或下令；到达参照区也不等于完成真实解围。

若`readonly_campaign_window.review_ready_global_priors=true`，公共配置已有可复核的计算先验，单位输入仍未知。先读完整公共基线，对照用户要求，只patch有差异字段；不需数值改动时仅更新`assumptions`记录复核说明。必须实际调用update并取得有效revision／configuration_hash，不能口头宣布通过；不要反复重写整份公共JSON或复制只读窗口。使用这些先验不等于历史数据已核实。

本片单位的`window_scope`说明实际投入范围与来源精度：`reported_action`是窗口内行动记载，不证明完整建制；`window_reference`仅为窗口参战参考；`prior_reference`不能升级成开局确证在场；`departure_only`只核启程，不当作同时到前沿。例如万家岭91师／预6师为各一部，149联队的临时指挥不改变其行政上级101师团；106师团计算聚合已含有机123联队时不能再给123联队配发第二份人员装备。方向参考、调令和后续历史节点不是开放模式已执行的命令。

局部阶段若模板包含`oob_coverage`，同样须填写每个父级的余部声明；它使用`historical-oob-coverage-1`，不是可省略的说明文字。未知余部用`excluded_unquantified`，不要用一个已知师或投入部替代全军。它不改变历史人数，也不自动生成未知余部。会战入口使用原`campaign_scope.remainders`，不要混用两套字段。

阶段中的`operations`和`relations`是有来源的事件—单位—地名及分时配属，不是宿主当前命令。保留其中未知坐标、时段精度与限制。运行时可调用现有`retrieve_history(kind=operations/relations/measurements)`分页读取冻结版本；默认读取当前阶段（回溯中为本事件绑定阶段），也可明确选阶段作历史比较。历史记录不能当成开放推演已经实现的战果，也不能把一部的临时作战配属写成全师永久改隶。

事件若有`unit_scopes`，须逐单位读取其`extent`、`scope`和定位依据：`elements`只表示所述部分部队，`reference`只是关联参考，`whole`才是该来源明确报告的全建制动作。即便是`whole`也不证明当前人数、装备和部署。旧事件没有此字段时范围未单列，不能默认全编制投入。不要因上级ID出现，就让全部计算叶子自动执行同一动作；这份资料也不替代本局命令、到场与余部校验。

新档案可显式选择`event_order=dated-events-1`。回溯按记载日期分组，同日仍保留来源顺序，概览和重叠区间另有说明；帧序号不是实际经过时长，不能从相邻帧推出双方已转移、会战阶段互不重叠或缺载小时。

`measurements`保留阶段数值的日期、指标、计量单位、统计口径和对象范围。`eq`是来源明确报数，`approx`仍为约数，`gt`仅为超过所记数，`range`为来源区间；均不自动成为本局状态。`replacement_basis`不是支队全体实到，`ordered_detachment`不是全师兵额或已执行数量，`reported_enemy_group`与`reported_retreat_group`不是整建制或全役损失；马匹不得换成车辆。必须连同`population`、来源及限制说明，不补齐缺载实力，也不据后续历史数值强制开放推演结果。没有测量记录表示缺载，不是零。

`reported_existing_strength`只表示来源在统计日和统计范围报列的现有数；`planned_replacement`是拟补充，不能当作已入队；`reported_strength_including_plan`包含拟补充，与前两类及各单位分项重叠，不再相加。沿用工具返回的`statistic_notes`、日期和`population`解释。1934年10月8日的现有／拟补充／含计划合计不能移作11月湘江开局、分摊师团或转成战斗损失；军委纵队等混合机关、直属及保障人员统计也不生成等额步兵。补入是否落实、后续实力与地理到场均需独立证据。

`documented_partial_reduction`是资料能明确的部分减员，不是完整损失的上限或全役阵亡；`reported_reduction`按所列期间和总体报列减员，不能改称战斗死亡、当作初态或扣兵配额。保持部分／总体、日期、对象及约数／超过关系，不把重叠的军团、分项和总数相加。军团部渡江不表示全军团或另在后卫的下级已渡江；接防命令不证明接防已经完成。已知清晨／黄昏事件分开读取，同日存在异文或未载先后的事件不擅自补钟点。

完整读取阶段事件时省略`query`，它是文字子串筛选，不是语义检索或通配符；空筛选可按`unfiltered_args`重新读取。所有后续页沿`next_args`保留阶段和定义摘要，不把当前帧切换后的另一阶段拼进旧页。

显式配置若包含`campaign_plan`，其`campaign-objectives-1`是双方多方向目标图，旧模板不自行升级。承担者引用实际执行历史/计算ID；未列余部、行政父级不能当作另一个物理单位。`operation_ids`仅关联冻结来源，地域、阈值和目标时间仍须说明估计，不能强制复刻历史战果。目标依赖与激活时点只控制评分，不自动发命令或替代真实入场/行军；持续任务使用下述独立execution契约，不能把评分图当自动命令。

来源阶段明确为`non_contact_transfer`且选择会战窗口时，使用同一目标图与入场模型，不创建敌方部队、仓库、受降或阻援区。每个参演军的`reach`地域与最少人员、随后`preserve`比例和`resources`粮弹下限须显式估计；保留全部承担身份与依赖。`campaign.objective.relief_regions=[]`、`campaign.surrender.enabled=false`，结束方式为`objectives`。仅此冻结来源范围允许未参演方`outcomes.node_ids=[]`；空目标不是达标，未到终点或补给不足仍应继续，转移失败不给虚构对手判胜。指挥参考和历史集体抵达节点不等于独立物理部队或逐军实际到达时刻。

需要同一世界连续阶段时，可在公共片显式增补`campaign_lifecycle`（`campaign-lifecycle-1`）：有序`phases`各填`id,label,goal_ids,minimum_duration_seconds,operation_ids,assumption`，并填`finish_policy,assumption`。目标ID引用现有目标图，每个目标至多归属一个阶段，前阶段不得依赖后阶段；无目标阶段必须有非零持续秒数。来源关联须来自冻结版本。`all_phases`要求全部阶段完成，`goal_outcomes`允许一方合法总目标提前结束；不得把双方相互排斥目标都设为必经阶段。阶段推进不补员、不刷新库存、不自动下令；估计阶段顺序不能冒称已证实的历史过程。单位片开始后公共条件锁定，旧配置不自动启用。

运行时调用原生`get_campaign_objectives(kind=nodes)`，沿`next_args`读完；`member_args`分页读取承担单位。`plan_hash`是固定配置摘要，`view_version`才是本轮分页版本，禁止混用。分别核对双方当前条件、连续达标回合及`resolution`，一方向达成不等于整场结束。里程碑已达成也不保证当前仍控制；保持时间按回合端点保守采样，不追补首次观察前的时长。结果由宿主读取AFSIM真实效果或通过守卫的DSH估计后评分，模型不得提交或改写`campaign_plan`运行状态。

若局部模板含`initial_command`，填写`historical-command-baseline-1`及`assumption`，说明采用所选阶段的来源关系作为开局指挥。身份/关系ID由宿主冻结绑定，不填写新番号或自由改写上级。行政关系与作战指挥分别保存；支援关系不授予主指挥权，临时任务群覆盖优先。新开局必须说明，旧冻结配置缺此项保留旧行为，不自动迁移；累计会战入口不能套用某个局部日期的配属。运行不按历史时钟自动触发后续转隶或命令。

会战窗口只有在`readonly_campaign_window.opening_command`显式声明时才采用起始阶段关系；公共与最终复核片可见冻结的阶段、关系ID、来源及适用说明。填写`initial_command.assumption`说明这是模型开局选择，零时计算边界不等于史实发令或全员实到。没有此声明的旧窗口保持原指挥契约，不能自行套用局部关系；此字段也不授权模型修改父级或按后续史料日期自动下令。

查询当前可指挥下级用`get_force_organization(kind=members,hierarchy=command,node_id=...)`并沿`next_args`读取；`hierarchy=historical`仅查行政参考。节点同时保留`parent_id`与`command_parent_id`，不能因161师一部临时配属66军就声称完整161师永久改隶。临时抽调后原上级有效成员减少，任务回执保存当时实际指挥链。

成员观察版本`force-observation-2`明确区分：`items[]`每项是一个执行成员，`command_id`是该成员的命令ID；`command_chain`是该成员从最高上级到直接上级的祖先ID序列，不能用本页各成员的`historical_unit_id`拼成上级链。`command_path`按同顺序给上级名称、类型与依据；`administrative_path`始终仅为行政参考。空链表示本局未绑定上级，不证明历史上不存在上级。旧局`legacy_administrative_fallback`是软件沿行政树授令的兼容依据，不是新核实的历史开局指挥；临时配属优先，旧冻结账不重算。

`available`只表示物理可用；`operational_status=waiting_arrival`和`arrival_wait_seconds`说明尚未入场，不能提前机动或开火。`ready`也不代表资源、射程和调用者权限都满足，仍经原有动作校验。观察与解释均不提交组织或命令。

节点查询的`execution_count`和`totals`按本次`hierarchy`选择：command只统计当前有效成员，historical统计行政参考。`command_execution_count`保留开局/兼容指挥结构覆盖，可能包括已抽调下级，不能当作当前可授令数；`historical_totals`不可与当前汇总相加。顶层`totals_scope=all_deployed_leaves_not_selection`说明顶层totals是全局投入总量，并非所查询节点总量。

新建任务群使用会话内短引用（如`task:7`），以减少机读ID抄写错误；`reference_scope=session`和`session_id`限定其作用域。旧UUID引用保持有效，不迁移旧群；沿阶段继承时连同组织修订一起携带。不能从别的战局拿同名短引用下令，也不能缩写任何既有ID。祖先顺序只按`command_path`读取，不按编号大小推断层级。

运行任务群查询使用现有`get_force_organization(kind=members,node_id=任务群或历史节点ID)`，沿`next_args`完整分页；返回实际`command_id`、`leaf_key`和`calculation_unit_id`。后续页必须带返回的`revision`；修订变化须重新读取，不按同父番号猜测计算分队归属。

兵团分工可通过原生只读工具`preview_force_task`检验：提供`group_id`、`task`及默认false的`replace_existing`；沿`next_args`分页，后续页保持`preview_hash`。`task.kind`支持uniform/advance/assault/defend/withdraw/sustain；机动任务须有明确地图目标，assault还须有敌方`target_id`。`roles`可为下级指定maneuver/fire_support/engineer/reserve/sustain；这只是当前分工，不能改写历史兵种或凭空增加装备。

逐项区分候选`order`与`existing_order`：`manual_kept`实际保留原人工命令，候选进攻并未生效。工具不能提交命令或预测战果；用户审查确认后才进入原有命令队列。每叶子仅一项主要动作；弹药、射程、禁火和未到场仍有效，工程/运输未指定时明确等待，不承诺长期自动任务链。回执中的`task_context`和轨迹中的`force_task_plans`用于追溯原任务与当时指挥关系，不能将人工任务包装成自主模型决定。

显式持续任务使用`execution.version=force-task-execution-1`，与旧单次任务区分。`preview_force_task`可携带完整execution草稿：`label`、`not_before_turn`、`after={mode:all或any,task_ids:[],goal_ids:[]}`、`finish`及`assumption`。finish为`{kind:arrived}`（仅全员机动）、`{kind:goal,goal_id:己方已登记目标}`或`{kind:turn,end_turn:整数,minimum_executions:正整数}`。沿用前端地图目的地与现有任务分工，不通过文字编坐标。用户确认后由宿主逐轮使用原命令系统，工具本身不提交任务。

已确认任务读`get_force_tasks(kind=tasks)`，成员用返回的`member_args`，状态事件用`event_args`；各页保留`view_version`，过期从第一页读取。任务ID只从工具复制，不用任务群ID或目标ID替代。应用队列已接受不等于部队实际收令；次数按选定后端回执，DSH仍是估计，执行次数不等于杀伤或工程效果。人工改令后不自动重新接管；当前指挥改变时停止旧任务派发。等待前置的预备力量保持明确待命。显式同世界`campaign_lifecycle`阶段里程碑保持原任务与实体，不自动重开初态；旧相邻阶段续接不能代替该路径。真正场外、换装重编及在途转换仍有限制，不能将拒绝静默改为重开满编局。

`force_scope=phase`保持已核阶段在场约束。`force_scope=campaign`且没有`readonly_campaign_window`时是用户显式选择的累计参战序列部署估计；有窗口则仅采用本窗固定候选，两者都不得解释为同日已核部署。保留所选不重叠地面身份和史料中的上级关系；指挥机关只汇总，不另外生成战斗平台。未载下级番号不能编造为史实。

会战模式必须填写`campaign_scope.planning_end`和估计依据，以及每单位`campaign.arrivals`、工事参数和多个方向的`relief_regions`目标；不得缩回四单位占点。`planning_end`约束初始到场计划，按目标结束的开放过程不因此强制重演历史结果。未知兵额、装备、部署须逐项标为估计，不以战役总数反推某日满编。

需要更细粒度时，优先使用有来源的下级编制；明确缺载时才用互斥计算分队。`formation-partitions-2`显式提供每父最多32分队、每方256叶子的会战容量；原v1仍为8/24。人员、分类装备、五类绝对库存必须守恒，父单位不重复执行。运行中任务群是临时配属，读取`get_force_organization`核对历史建制和现有群，不把临时配属写成历史改编。所有状态保存在宿主，按需分页观察，沿用DSH会话和压缩能力。

## 结束方式与史料时间

严格遵守`get_scenario_basis`给定的`goal.termination_mode`。`objectives`表示按目标完成：达到程序目标并连续保持`required_turns`轮，或目标方失去全部可用人员时结束。`deadline_turn`此时仅表示滚动规划参考，不能用来自动判负。迟滞、组织存续以及联合战役目标也以连续满足条件为准，不等待史料截止日。`deadline`保留限时训练的截止判定；缺少此字段的旧存档保留原规则。

`objectives`模式的史料时间窗只约束历史初态起点，开放过程可延伸到窗口以外。延伸是当前编制、装备、资源和已登记规则下的反事实估计；不得补造后续援军、事件或历史结局。史料精度为日不意味着计算步长只能为1天；30分钟离散计算不表示掌握了该时刻的历史命令。不得为了容纳史料窗口把目标期限强制缩成1轮。

## 资源预算与地形约束

显式窗口中的`campaign_plan`若使用`defend`，`condition.region`表示本方就绪兵力部署区，不是排他占领区；敌人在此接触不直接判失守。`against_node`固定引用对方已有`reach`节点的突破核心及最少到达人数，必须保留模板绑定，不能改指另一轴线。敌方在核心满足物理人数条件就中断本方保持，即使对方节点未激活或尚未保持足够时间；退出后重新采样计时。本方后方待命、未到场、失能、场外或压制超过门槛的部队不计入防守人数。部署区、突破核心、人数与时长须分别说明估计依据，不通过缩圈或改门槛保证历史结局；旧`control`仍要求地域无敌，不隐式替换旧窗口。

全量校验回执包含`resource_readiness`。按每单位的粮食小时、弹药工作量支持的有效火力分钟、炮弹支持的炮击分钟核对任务，不能只看库存数字。长窗口持续作战应说明预计有效开火时长、补给节点库存与运力；如果预算不足，应修改显式估计参数并重新校验，或说明可执行的短促接触/撤离目标。不能把一轮60分钟写成持续射击60分钟，不能将弹药工作量当炮弹发数，不能为了匹配历史累计伤亡自动增伤。

可选公共条件`terrain_model`使用`local-terrain-1`：`assumption`、`barriers`、`roads`。每条障碍含`id,a,b,blocks,source`，其中a/b是lat/lng，blocks只能为movement/direct_fire；道路含`id,a,b,width_m,speed_factor,source`。这是有限线段与直线道路走廊，不是DEM。只有有出处或明确标注估计的坐标才能填写；不能把地名中心当山脊、把没有登记的道路视为存在。障碍阻断移动和直射，间瞄另受射程与资源约束。曲折道路需拆分位置命令。

## 可选的时间保障模型

另可显式选择 `personnel-rations-1`，其字段是 `ration_kg_per_person_day`、`food_kg_per_work`、`carried_kg_per_committed_person`、`move_factor`、`shortage_fatigue_per_hour`、`recovery_hours_per_fed_hour`、`incapacity_after_hours`、`incapacity_fraction_per_hour`、`assumption`。**不含**旧版的 `food_work_per_hour`。需求=当前可用人数×kg/人日×小时/24÷kg/工作量，move再乘倍数，不再次乘分队份额。人数、干粮／熟食质量口径及配给与实际摄入必须在assumption说明；缺载使用显式估计，不能声称历史配给或医学标定。

新模型必须启用 `split-stocks-1`，`food_kg_per_work`须等于`rules.ton_per_supply_unit×1000×supply_distribution.food_mass_share`。它是既有粮食库存的唯一质量换算，不另提交或维护food_kg库存。单位携行容量=committed×carried_kg_per_committed_person（kg），对应food工作量上限=该容量÷food_kg_per_work÷编组份额，不再默认100。若该上限超过编码范围100，必须明确提高kg/工作量并同步运输换算，不截断容量或库存。各军人数不同，应分别检查初始库存不超过自身容量。源事实仍未知时不把估计数量冒称实编。

质量份额已计入`food_kg_per_work`，换算初粮时不能再乘除`food_mass_share`。例如6000人、估计0.3kg/人初粮、125kg/工作量、0.5kg/人携行上限：初粮1800kg应填`food=14.4`，上限为24工作量，不是28.8或48；这些仅是换算示例，非历史配给。分片提交会直接校验本片容量，错误的`food_loading`回执给出单位、现提交质量与上限；修正该片输入后再提交，不改变锁定公共参数、不截断库存，也不能口头宣称已修正。

新模型按轮初人数计算需求；定时补给按段初人数，段间扣除已计缺粮失能；战斗减员影响下一回合需求。减少人数不会自动删除粮食，容量按冻结投入人数登记而非现有人数，不代表实际可用携行人力。供粮每小时消减`recovery_hours_per_fed_hour`小时旧缺粮债，不是“需要若干小时才能恢复”。归一化资源账与七项保障回执沿用现有字段，state和ledger的version均使用所选版本。

新建长时段想定可在公共条件 `support_dynamics` 显式配置 `version:"time-sustainment-1"`、`food_work_per_hour`（0.001–100，待命每小时归一化工作量）、`move_factor`（1–10）、`shortage_fatigue_per_hour`（0–100）、`recovery_hours_per_fed_hour`（0–10）、`incapacity_after_hours`（1–8760）、`incapacity_fraction_per_hour`（0–0.1）以及非空 `assumption`。这些是教学估计，不是经史料或生理试验标定的阈值，必须说明依据和敏感性范围，不把示例数值冒充史实。

启用后，先消耗轮初粮秣，再累计未供粮时长；轮末到货不能回溯抵消短缺。缺粮影响疲劳，超过显式阈值后按初始人数和缺粮暴露增量累计非战斗失能，小数余量跨回合保留；不能据此增加阵亡。AFSIM负责执行并返回回执，DSH通过态势工具读取回执决定后续行动。关闭AFSIM时由DSH提交同模型收支与保障回执，宿主只校验，不代算战局。模型未定义额外气候/疾病失能。

旧存档无此字段时保持原每回合耗粮与原生缺粮规则，不自动迁移。当前粮弹补给包仍绑定，分类运输与休整等其他规则不因此宣称全部实现时间连续；不得承诺完整后勤标定。分片生成可在globals提交该对象，单位分片不能改变它。

## 分片配置模式

先读取skill与`get_scenario_basis`。若返回`workflow=staged_historical_configuration`，使用本节流程：完整配置在宿主，各会话只操作已分配范围，最终不输出整场JSON。

- `part=globals`：填写`configuration`中的公共条件。`actor_counts`是双方计算单位数；已知位置参考帮助确定战区范围，不代表所有单位的部署。禁止提交actors、format或phase_id。
- `part=actors:N`：只填写`assigned_actor_ids`与`configuration.actors`中的最多4个真实单位。遵守`readonly_global_configuration`，不得改公共参数或访问其他分片。已知事实只读，缺载参数按下文逐项说明估计。
- 两种填写任务都调用`update_scenario_configuration(revision=当前revision,patch=本片填写内容)`。公共参数须一次填完必需值；单位补丁形如`{"actors":{"已分配真实ID":完整单位参数,...}}`，必须覆盖本片全部ID。工具会验证该片后才保存草稿；失败时按error修正并重试，不能把updated=false称为成功。版本过期先重新读取basis。
- `part=final`只读复核：调用`validate_scenario_configuration()`，不传configuration。只有`scope=complete_configuration_and_native_template; not_live_load`且valid=true才表示全量模板通过；分片通过不代表全量通过或AFSIM已实际装载。
- 每个会话最终只输出`{"revision":工具返回的整数,"configuration_hash":"工具返回的哈希","explanation":"本片估计依据与限制"}`。不得自行生成哈希；不要回传完整参数。AFSIM实际装载由宿主后续执行。

若basis没有上述workflow，使用末尾的完整模板提交方式。以下兵种、时空、后勤与历史事实约束适用于两种模式。

## 参数与史料约束

新建模板默认提供`supply_distribution`，保留或按用户说明编辑：`version:"split-stocks-1"`、`food_mass_share`（0.01—0.99）、`priority`（food/ammo）及非空`assumption`。这是明确的运输估计，不是历史物资重量。初始support.stock每包拆为各一工作量粮弹，此后分别扣仓、共享运输质量额度；未运的另一类保留，不浪费、不凭空补齐。满弹不阻止补粮。stock/delivery表示按质量份额折合的包当量，不能称为粮食到货数；实际分类到货见food_received/ammo_received。旧冻结定义没有该字段时仍采用原绑定补给包，不静默迁移。

调用`get_scenario_basis`读取本次固定阶段、真实ID、番号、已知事实、来源、缺载项、地名参照和`configuration_template`。身份、上下级、阶段到场由宿主绑定，只填写模板参数，不返回或改写档案。必须覆盖所有actors，不能增删、改名或同时累计上下级。普通接敌阶段缺少双方已核单位或海空未绑定时说明缺口，不用教学种子兜底。

若basis或phase的interaction.kind为non_contact_transfer，仅配置active_teams的既有actors，另一方保持空，不虚构蓝方、守军或目标。另一方support只是格式占位，stock和inventory必须全0，不生成该方仓库；position可填写计算中心但不能称为在场设施。目标使用在场方的crossing或breakout。场外追兵保留在excluded_references，不提前部署。没有敌方目标就不下fire/bombard/suppress/air_support命令，不能以虚构交战或伤亡演示活动。

模板的null不是零，是待填值。历史缺载人数、分类装备和坐标可估计，必须在每个actor.assumption、area.assumption和总assumptions说明其模型估计性质与范围，不能称为历史实到/真实阵地。遵守用户约束，按师/旅/支队实际层级估计，不能一律3000人。源码提供的规则是未标定聚合模型系数，采用或修改均说明；不得宣称已证实真实伤亡效果。已知事实不得改动。

完整保留本片可编辑模板字段，不增加WSF/脚本、名称或史实对象。非分片模式的`configuration`是完整模板对象，分片模式只提交本片可编辑字段；两者都不是teams：

- actors每项填写正整数personnel；五类equipment的非负整数；十进制度position；type用步兵、装甲或炮兵等已登记地面兵种；speed为km/h、ground_control_radius_km为km。attack_range_m只表示fire的直射范围（米）；间接火力单位的自卫小武器范围不能超过本局rules.direct_range_m，不能沿用数公里榴弹炮射程。坦克等直射武器可按说明单独填写。火炮间接射程单独使用rules.artillery_range_m并下达bombard/suppress。
- logistics.food/ammo为0–100工作量。formation.role只用infantry/armor/support；fatigue、suppression、entrenchment、signal、intel_confidence为0–100整数；dispersion_km2允许0.001至10000平方公里，不能因载荷小而填更小面积或0；protection为0–1。燃油、备件、材料、炮弹、防空弹、装填剩余周期、情报分钟为非负整数。不具备的能力可显式设0，说明依据。校验失败按error指出的字段和范围修正，不反复试改无关布尔开关。
- formation.motorized逐单位选择true/false；徒步、驮运不应因燃油为0停走，汽车队则受燃油约束。rules.motorized只是旧配置的整体回退，新模板必须填明每单位方式，不能把整场双方都当成同一机动类型。

### 必要的分岸与分遣计算

公共条件`partitions`可选，默认不填写，也可保留`{version:"formation-partitions-1",groups:{}}`。只有用户明确要求或本阶段证据需要时，按已有父历史ID配置互斥分队，不创建另一套历史番号；公共条件补丁可添加此可选字段。v1每组填写assumption及2–8个parts；显式会战v2为2–32个parts（每方最多256叶子）；每项填写id（小写字母数字下划线）、label、personnel、position、equipment五类整数、resources五类绝对库存、dispersion_km2、assumption。人员、分类装备和绝对库存分别合计等于actors父单位输入；父单位不会额外生成一份兵力。分队位置另作估计，不能把未知坐标写成史实。单位分片须将父personnel/equipment/formation绝对库存填写为公共条件各分队之和。

分队继承父单位type、速度、射程及归一化粮弹覆盖；仓库到货与粮弹消耗按初始人员占比折算为父编组等效工作量，不能各自领取一整份父库存。真实历史父编号与来源保持不变，分队显示名标注“计算分队”。这只描述分布与独立指挥，不能声称已模拟舟筏航行或自动分配未知历史先遣兵力。突围、渡运目标须同一父单位所有仍可行动分队满足，不能拆成两份计两个父单位。
- 番号中的“骑兵”不等于骑马作战。例如1950年美骑兵第1师保留原番号，type按当时步兵、装甲与支援能力填写；不能赋予古代骑兵速度或近战机制。配属坦克排、炮兵连须保持各自来源范围，不能扩大成全营。
- clock.start为所选阶段内的当地`YYYY-MM-DD HH:MM`；缺载钟点作为假设说明，不编成史实时刻。basis若含time_step_constraint，time_step必须等于该启动页选择的时长，不能被自然语言中的其他跨度或模板默认值覆盖。公共条件、单位分片与最终复核均遵守此约束。仅deadline模式需要按阶段截止调整deadline_turn；objectives模式不因史料窗截止而缩短规划或擅改步长。无此字段的旧调用才自行明确选择跨度。
- 若有execution_window，初态起点必须在窗内。仅deadline模式要求clock.start加deadline_turn×time_step不晚于end；objectives模式可以延伸，不能把史料窗当作强制停战时刻。后续参战与场外参考保留于档案，但不添加到actors，不提前入场或虚构航空资源。
- area中心、半径和terrain_factor均为明确模型参数。行军预算=速度×回合小时数÷terrain_factor；1为基准，大于1会减慢，小于1会加快，不能把小于1解释成山地迟滞。分片模式的known_reference_extent概括全部来源位置参考范围，不能仅按显示的前16条参考设置战区；它不是精确部队部署。地名坐标仅作定位参考，不等于部队坐标；各方部署、补给点、目标都应在合理战区，允许预计机动/接敌，不把师级部队挤在几十米内。
- actors的facts.position若为deployment_area_reference，估计位置须落在该区域及uncertainty_km范围内；它是粗区域，不能声称精确阵地。优先使用本阶段部署区域，不能把县城参考点当作伏击沟。人车展开与射程按团、队实际层级估计，数小时持续交火应同时考虑弹耗及隐蔽/补给条件。
- 两方support分别填position、stock及五类inventory。资源单位遵循模型：fuel_liters升、shells/aa_rounds发、spares/materials模型工作包；stock是保障工作量。
- goal.team明确填red/blue，表示需要达成该目标的一方，不等于用户操纵方或固定胜方。assault/delay/breakout/crossing支持任一方；rail/underground/reception目前仅红方绑定，不能将未实现的方别切换冒称可用。蓝方突击/突围不能套成红方进攻。若basis含objective_guidance，先核对所选阶段的任务建议、来源和not_covered；用户可改变开放推演的目标，但需说明偏离，不强制历史结局。马良山10月5日仅涉及第一线，不能提前计入次日巩固；上甘岭表面地域不等于坑道控制。
- goal.profile与rules.goal_profile一致，只用assault/delay/breakout/crossing/rail/underground/reception。objective、exit、radius_km、deadline_turn、required_turns、required_survivors全部填写；保留启动页给定的termination_mode；目标和相关出口须在计算地域内。仅deadline模式要求连续控制回合不超过截止回合。描述可计算的局部目标及限制，不冒充全战役胜负。存续门槛是目标方可用编组数（不是人数），不超过该方actors数量，在goal和rules保持一致。程序会依据参数生成目标说明，不能凭文字宣称另一套胜负。
- 保留era与版本/categories。仅当模板含aviation时，逐ID填写initial（committed架数、ordnance和fuel工作单位）、entry（计算入场/返场点）、rules（计算假设）及assumption；航空身份和来源由宿主绑定，不填入actors，不将某次出动架数当作初始库存。模板含availability时必须填写air-availability-1版本、当地start、end与估计依据；end可为null表示持续可用，不能留空start或把累计参战当作开局到场。入场start在clock.start与campaign_scope.planning_end之间；这只是计算假设，不修改史实presence。任务只有在可用时段内才能下令并返场，后端按程序时钟校验。有具名资源时可按用户意图开启air_support；无aviation时必须保持false，不能使用固定教学飞机池。bridge_enabled默认false，facility只是计算汇总点；把其lat/lng设为area.center，不能凭空画桥或施加渡桥约束。其他固定数值保持模板即可。

会战范围同时含`campaign`并选择`delay`时，在公共条件中明确填写`campaign.objective_policy="defensive-delay-1"`。它按已入场可用编组门槛、已入场人员相对于已入场投入的`min_force_fraction`、敌方已入场单位未到出口600米内判定；不要求夺占据点或阻援区域。未来部队不计存续，不得靠累计参战名单满足目标。与`campaign_plan`目标图不混用。旧配置无此字段仍保留旧夺控语义，不能声称已按新迟滞规则运行；需明确修订再验证。此阈值是建模假设，不是历史反扫荡存续的完整复原。

非分片模式提交前真实调用`validate_scenario_configuration(configuration=完整参数)`；依据返回错误修正，再校验。最终只返回`{"configuration":完整参数,"explanation":"估计范围、时空/目标选择与未覆盖史实"}`。分片模式遵守开头的小回执格式。两种模式均不得生成本轮战损或修改现有战局。

执行引擎可为narrative或afsim；前者只做配置/来源校验，后者由宿主调用既有DSH MCP控制器完成AFSIM原生装载。不要自行调用shell或原始MCP执行，不创建第二个运行时。正常生成须留下实际原生工具轨迹；分片模式还须有每片草稿更新和最终全量校验，不能只声称调用。

## 完整战役过程（来源阶段明确要求时）

若phase.input_constraints存在，必须读取其personnel与entries。personnel中的reported是有出处的规模口径，minimum/maximum是本版本明确声明的建模筛选范围，不是精确史实名册；actors的人数必须在范围内。不能以“估计”或合计总数为由把约40人扩成260人，也不能把该范围回填进facts。

entries中每个被引用单位的计算叶实体必须在campaign.arrivals条目（或parts条目）填写独立reference_id和event_kind，完整覆盖该单位entries，不能重复绑定、借用别的单位参考或漏批。historical-input-1的entries均为接敌参考；historical-input-2逐条声明reference_kind，不能混用两类时点。

- reference_kind=contact：前沿接触/到达参考。event_kind=battlefield_entry时，not_before须在参考时间窗内，计算初始位置须在region内；这是前沿入场模型，不模拟此前驻地行程，不会到时瞬移。event_kind=departure时，not_before须提前，按speed/terrain_factor至少留足到参考区的最短行军时间；实际指令、通信、疲劳与敌情仍会影响抵达。不能把15:15已接敌的记载当作15:15才从几十公里外启程。
- reference_kind=departure：只有启程时段依据，region为空；必须选event_kind=departure，not_before在earliest—latest内。不能以凌晨可行动代替下午出动，不能编造一个接敌区域或把启程窗口当作抵达时刻。窗口是有明确说明的建模约定，解锁并不自动下达移动命令，开放推演仍由DSH／操作者决策、AFSIM执行。

region若存在是明确标注的建模区域，不是已测绘史实阵地。partitions若分4批，就在arrivals.parts逐批引用4个不同reference_id；父级可只保留not_before和assumption供未分队配置使用。不要为了通过校验虚构额外参考批次。

模板包含campaign时，globals须同时填写这一完整对象，不能省略退回四小时占点。arrivals与fortifications覆盖全部actors历史父ID；参战名单表示在整个窗口参加，不表示开局都在据点。not_before按已选来源口径及当地时间填写，时刻缺载时标为估计。已定义partitions才可在arrivals对应父ID添加parts，逐分队填写not_before/assumption，用于分批援军；各批共享父兵力账，不另增一份全团。

globals的actor_index提供全部父ID、名称、方别与层级，用于分配到场、工事和必要的互斥分队。该索引不是完整名册或数值事实；不要从ID猜测新番号或把累计参战者同时放进据点。单位分片只读取自己的详细参数，遵守公共条件已分配的人员、装备和绝对库存合计。

注意两种parts结构不同：`partitions.groups[父ID].parts`是带`id`字段的分队列表；`campaign.arrivals[父ID].parts`是`{"分队ID":{"not_before":"当地日期时间","assumption":"依据"}}`对象，不是列表。若要求分批入场，必须保留后者的不同时间；仅拆成四个分队而全部继承同一父时点不满足分批要求。`relief_regions`的每项仅含`center:{lat,lng}`和`radius_km`，不添加name、assumption或其他字段，依据统一写在objective.assumption。收到updated=true和next_action=finish后直接返回回执结束本片，不再重写已验证参数。

fortifications逐ID填写integrity（0–100）、degradation_per_shell（0–100）及assumption；无永久工事可取完整度0并说明。surrender填写enabled、range_m（1–1000米）、suppression_threshold和ammo_threshold（0–100）及assumption。允许受降不等于预定俘虏数量。

goal.profile与rules.goal_profile使用assault。据点位置仍只填写goal.objective/radius_km。campaign.objective仅填写1–6个relief_regions（各含center:{lat,lng}与radius_km）、min_force_fraction（0.001–1）及assumption，不另填town。objectives模式要求目标方同时控制据点和所有阻援区域、保留规定比例人数并连续达标required_turns轮；deadline模式在截止回合检查这些联合条件。不能只占一点就称为成功，也不预定历史胜方。所有地点必须位于计算地域内。campaign.assumption说明全程覆盖、来源分歧和未知量。过程状态不属于配置，禁止提交active、captured_this_turn或预生成伤亡。

## 补给预算

### 可选定时补给

若`required_models`含`scheduled-supply-1`，globals必须提交完整`supply_schedule`，不能只在说明中承诺。字段为`version:"scheduled-supply-1"`、`period_seconds`（60—86400、10秒整倍数）、`passive_work_per_hour`和`resupply_work_per_hour`（0—1000，后者不低于前者）、`convoy_speed_kph`（0.01—200）、`loading_hours`（0.01—24）、`warehouse_tons_per_hour`（本局每个仓库ID到0—1000000模型吨/小时）及非空`assumption`。历史计算仓库ID是`red-historical-supply`／`blue-historical-supply`；单方转移只填实际在场方，不能为格式占位新增仓库。

必须同时有`support_dynamics`与`supply_distribution`。本版为已运行管线的定时聚合服务，`rules.bridge_enabled=false`；共享渡运货运、具名车队在途及运输燃油未接入，不能打开设施约束后静默略过。每轮最多96次到货，需缩短回合或有依据地调整周期。既有定义不自动启用。

到货按战局累计时钟触发，不在每轮重置；同仓各部队共用该仓每周期装卸吨位，运输上限另受车辆、距离和周转速度约束。费用按到货前／后时段核对，轮末不额外补发。普通保障与主动补给每小时工作量、仓储和车辆必须有估计依据；本开关不补足史实资源、道路或人员质量标定。生成后仍由完整参数验证与实际执行验收。

生成公共仓库和各单位粮秣时，须结合截止回合与待命/机动任务检查预算。最终校验返回的sustainment是当前冻结规则下的只读库存估算：全部待命、假设现有库存可达，仍有短缺就应在解释中明确指出；零缺口不证明运输和分配可行。待入场单位当前也耗粮，粮弹绑定补给包可能因满弹而不能补粮。不能将这些工作量称作历史口粮重量或以耗尽后的固定减员冒充历史饥饿损失。缺载库存仍须标注估计依据；不要为保证胜负而偷偷增发物资，用户修改参数后须重新校验。

## 机动与疲劳反馈

若required_models含`movement-feedback-1`，公共条件必须填写`movement_feedback:{version:"movement-feedback-1",assumption:"明确采用原生通信/疲劳/压制/兵力/燃油约束，系数为计算估计"}`。这个模型不补造兵额或历史战损；不调整名义速度来保证结局。执行时普通陆地有效预算扣除原生等待，疲劳按实际陆地公里取最接近整数、半数取偶数；休整按已选择保障模型的回合尺度恢复，缺粮债只给疲劳下限。桥梁等待/服务与舟艇装载/航行/登岸分别核验，船载位移不冒充乘客陆地行军或地面耗油。旧配置不自动启用，阶段续接不能静默删除或更换。参数通过校验后仍需实际后端验收，不将这个开关称作历史生理标定。

## 渡河通道参数

仅当本阶段或用户需求包含已说明的跨河过程时，在公共条件添加facility.crossing_model，使用formation-crossing-1：barrier和banks各有a/b十进制度点，banks连线须跨越有限barrier；所有点在计算地域内。throughput_work_per_hour、equipment_work（五类装备）、build_progress_per_engineer_hour、supply_work_per_unit和assumption全部填写，rules.bridge_enabled=true。缺载几何与能力明确标为估计，不将现代水库岸线称作历史渡口。旧配置可不含此字段。

throughput_work_per_hour和supply_work_per_unit均为0.01至1000000；build_progress_per_engineer_hour为0.0001至1000。即使本局没有工兵或只用舟艇，这些已登记系数仍须合法；没有工兵不会自动发生施工，不用把系数改为0表示禁用。facility.progress=0与rules.bridge_enabled=true可同时表示无已成桥但通行过程受约束，不能为了用船而关闭通行约束。

需要舟艇时，可选添加crossing_model.ferry，版本formation-ferry-1；boats为1至8艘，逐艘声明id、name、team、seats、equipment_work_capacity、speed_mps、load_seconds、unload_seconds、initial_bank和assumption，并填写总assumption。id用不重复的小写字母数字下划线。每艇每次只载一个容量允许的互斥计算分队，不能复制整团兵力或虚构船员；不适载的大编组须明确划分或调整有依据的能力。舟位、装载、航行、卸载、空艇返航为独立过程，登船不等于通过。此可选模式不自动切换为桥式通行，尚未实现仓库跨河货运、波浪水流、沉船或船上射击；不能声称复原了完整强渡/桥头战斗。不要在输入配置写ferry_state，状态由初态编译和实际执行回传；不需要舟艇时省略ferry。

同一有限河线需要多个独立通道时，可选facility.crossing_network={version:"formation-crossing-network-1",sites:[其他设施]}；加上主facility共2至8点。每个其他设施完整声明id/name/lat/lng/progress/integrity/materials/capacity/used/crossing_model，不嵌套network；id唯一、used=0，barrier与主设施完全一致，banks、吞吐、装备折算、工程速率、补给工作量与估计依据分别填写。部队和仓库仍只声明一次。独立队列同时在同一AFSIM世界执行，部队与跨河货运共同占用各点容量；按入口—出口—目标距离最短选点，同距按冻结顺序，同一未完成指令保持原点，不能借用别处工作量。工兵行动选择最近岸点所属设施。此版不含多渡点具名舟艇、曲折河网或连续跨多条河流，不得静默降级；没有充分几何依据时保留独立局部场景，不虚构整场联动。生成后仍须验证，版本可用不等于战役史实已验收。

若get_scenario_basis返回required_models包含formation-ferry-1，这是用户通过界面明确选择的生成要求。globals阶段必须实际写入facility.crossing_model.ferry，不能只写partitions或在说明中承诺稍后填写；漏项的公共配置会被拒绝，须在当前分片修正。单位分片仍不能修改公共条件，最终复核不能把缺项草稿声明为完成。不按自然语言出现某个关键词自动启用模型。

新模型按可用人数加装备折算的共享工作量排队，未完成留在入口，跨回合保留；补给和编组共享容量，施工按工程数和有效小时。若目标要求实际渡河，使用crossing：足够编组取得completed回执并进入目标区；不能仅占领附近就声称通过。模型尚不表达舟艇突击、单兵分岸或桥头堡夺取；对此类未支持史实过程必须明确缺口，不能把桥已建成的后续通行冒称完整强渡战斗。

若 `required_models` 包含 `time-sustainment-1`，必须在公共条件填写完整 `support_dynamics`；仅在说明中承诺不算实现，漏项或非法值会拒绝。不得静默回退每回合耗粮。需要时间保障时依据用户显式选择，不按自然语言关键词自动开关。

若要求 `personnel-rations-1`，必须使用同名版本及上述质量／人数合同，不得换成按编组率；两种版本不能同时要求。定时补给可以配合任一时间保障版本，模型选择仍须明确且一致。

已显式绑定`campaign-lifecycle-1`的运行战局使用`get_campaign_lifecycle`沿`next_args`读取阶段，`view_version`绑定本次观察。阶段目标在激活后的物理回合评分，用`get_campaign_objectives`核对；`waiting_phase`表示尚未采样，不是条件为假。阶段只调度里程碑，不调兵、不改变实际参战单位集合，也不补员或重编。`all_phases`要求阶段完成再按总目标结算；`goal_outcomes`允许双方总目标提前结算并中断阶段链。不能通过写入阶段完成、复制世界或虚构未来单位推进流程。此版本由显式参数绑定，公共分片生成器尚未自动编排整套阶段，不在说明中承诺已经配置。

## 作战区边界与登记通路

可选`operation_boundary`版本`operation-boundary-1`只用于已有会战目标图。它在原仿真世界内另列作战区圆形边界及本方直线出入通路，参数须说明来源或估计；不修改历史事实、默认版本或旧局。跨界须明确`move`与`participation`意图，先到通路区内点再按登记端点退出／返回。实际到达区外点后宿主记`offmap`，沿通路到达区内点才恢复作战；不能通过普通移动或修改登记冒充出入。场外仍保留实际坐标、伤损、库存、时钟、保障消耗与受击可能，不是退役、删除或免费恢复。模型不写`unit_participation`。`get_afsim_observation`提供区内外摘要和逐单位参与状态，完整冻结通路读`get_afsim_observation(detail=true，按所选单位阵营返回通路)`；沿用现有工具、会话、事件及提交事务，不另造战场状态。此版直线通路没有DEM／道路共享容量，也不支持开局场外增援或区外空间目标，缺失应拒收。
