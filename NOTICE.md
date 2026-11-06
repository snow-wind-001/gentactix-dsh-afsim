# 项目署名与致谢

本仓库 GenTactix-DSH 的开发维护单位：**沈阳理工大学装备工程学院深度学习实验室**。

本项目基于 [pystrategylab/Gentactix](https://github.com/pystrategylab/Gentactix) 扩展。
感谢原作者开源 GenTactix，为历史推演、地图展示和确定性裁决提供基础。
原项目的 MIT 许可证和版权声明完整保留于 [LICENSE](LICENSE)。

DSH 集成依赖 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。
第三方组件和历史资料分别遵循其原有许可证及来源说明。单位署名不表示上游作者或服务提供方为本项目背书。

军事标图图例以项目矢量重绘及独立来源元数据维护，可关联用户本地提供的《军事标图技法》转换素材。原书扫描页面、组合图和自动笔画组不随安装包发行；应用图例不表示军用标准认证、史实年代认证或继承原书商业授权。


## Docker分发组件

Docker镜像内的AFSIM 2.9运行集独立于本应用MIT许可证。发布方已声明取得分发授权；本交付未收到授权名称、编号或原文，不据此另造许可。原文件内的版权和传播/出口限制标记均保留，接收方须按相应授权使用和转交。公开源码不包含AFSIM本体，镜像及Docker文件访问请向 snowwind001@gmail.com 申请。详见 [AFSIM分发说明](docker/AFSIM-DISTRIBUTION-NOTICE.txt)。

DSH SDK/runtime 0.2.1rc5由固定上游提交及记录在案的三项打包修补构建；其MIT许可证和第三方声明见 `docker/licenses/dsh/`，版本、SHA和来源见 `docker/sdk-wheels.json`。SDK/runtime wheels作为发布资产提供，不包含开发者虚拟环境或个人配置。
