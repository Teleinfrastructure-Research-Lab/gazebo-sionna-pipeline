#include <memory>
#include <string>
#include <vector>

#include <gz/plugin/Register.hh>
#include <gz/sim/Model.hh>
#include <gz/sim/System.hh>
#include <gz/sim/components/JointPosition.hh>
#include <gz/sim/components/JointPositionReset.hh>

namespace
{
class PreloadJointPose final :
    public gz::sim::System,
    public gz::sim::ISystemConfigure
{
  public: void Configure(
      const gz::sim::Entity &_entity,
      const std::shared_ptr<const sdf::Element> &_sdf,
      gz::sim::EntityComponentManager &_ecm,
      gz::sim::EventManager & /*_eventMgr*/) override
  {
    gz::sim::Model model(_entity);
    if (!model.Valid(_ecm) || !_sdf)
      return;

    auto jointElem = _sdf->FindElement("joint");
    while (jointElem)
    {
      if (jointElem->HasElement("name") && jointElem->HasElement("position"))
      {
        const auto jointName = jointElem->Get<std::string>("name");
        const auto position = jointElem->Get<double>("position");
        const auto jointEntity = model.JointByName(_ecm, jointName);

        if (jointEntity != gz::sim::kNullEntity)
        {
          const auto positionVec = std::vector<double>{position};
          _ecm.SetComponentData<gz::sim::components::JointPositionReset>(
              jointEntity, positionVec);
          _ecm.SetComponentData<gz::sim::components::JointPosition>(
              jointEntity, positionVec);
        }
      }

      jointElem = jointElem->GetNextElement("joint");
    }
  }
};
}

GZ_ADD_PLUGIN(
    PreloadJointPose,
    gz::sim::System,
    gz::sim::ISystemConfigure)

GZ_ADD_PLUGIN_ALIAS(PreloadJointPose, "preload_joint_pose")
