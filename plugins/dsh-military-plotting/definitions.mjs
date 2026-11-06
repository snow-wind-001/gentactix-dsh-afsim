/** Native Cordis definitions, loaded by the existing GenTactix runtime plugin. */
export const definitions = [
 ['read_military_plotting_skill','读取军事标图skill、字段约定、定位点与图例使用边界。',{}],
 ['search_military_symbols','按军事对象检索已登记应用符号及本地原书参考编号；不返回未审核笔画组。',{query:{type:'string'},limit:{type:'integer',minimum:1,maximum:28}}],
 ['validate_military_plotting','只读校验标注草稿、几何顶点、已知位置和符号目录；不写战局或标注。',{candidate:{type:'object',additionalProperties:true}}],
];
