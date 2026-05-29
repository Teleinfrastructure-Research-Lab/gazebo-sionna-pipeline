#include <gz/msgs/image.pb.h>
#include <gz/msgs/pointcloud_packed.pb.h>
#include <gz/transport/Node.hh>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

struct Config
{
  fs::path outputRoot;
  std::vector<std::string> labelsTopics;
  std::vector<std::string> coloredTopics;
  std::vector<std::string> rgbTopics;
  std::vector<std::string> pclTopics;
  std::size_t maxGroupsPerCamera{3U};
  double timeoutSeconds{30.0};
  std::size_t stride{4U};
  double maxSyncDeltaMs{50.0};
  std::size_t maxBufferPerStream{18U};
};

struct PointRecord
{
  float x{0.0F};
  float y{0.0F};
  float z{0.0F};
  std::uint8_t r{255U};
  std::uint8_t g{255U};
  std::uint8_t b{255U};
  int pixelU{0};
  int pixelV{0};
};

struct ImageRecord
{
  gz::msgs::Image msg;
  double stampSeconds{0.0};
  std::string headerStamp;
};

struct PclRecord
{
  gz::msgs::PointCloudPacked msg;
  double stampSeconds{0.0};
  std::string headerStamp;
};

struct CameraState
{
  std::string cameraId;
  std::string labelsTopic;
  std::string coloredTopic;
  std::string rgbTopic;
  std::string pclTopic;
  fs::path rootDir;
  fs::path labelsDir;
  fs::path compactDir;
  fs::path gazeboCountDir;
  fs::path coloredDir;
  fs::path rgbDir;
  fs::path plyDir;
  fs::path metadataDir;
  std::vector<ImageRecord> pendingLabels;
  std::vector<ImageRecord> pendingColored;
  std::vector<ImageRecord> pendingRgb;
  std::vector<PclRecord> pendingPcl;
  std::size_t count{0U};
  std::size_t pendingSaveCount{0U};
  std::size_t nextGroupIndex{0U};
};

struct FieldInfo
{
  bool present{false};
  std::string name;
  std::uint32_t offset{0U};
  gz::msgs::PointCloudPacked::Field::DataType datatype{
      gz::msgs::PointCloudPacked::Field::FLOAT32};
};

struct SaveContext
{
  std::string cameraId;
  std::string labelsTopic;
  std::string coloredTopic;
  std::string rgbTopic;
  std::string pclTopic;
  fs::path labelsDir;
  fs::path compactDir;
  fs::path gazeboCountDir;
  fs::path coloredDir;
  fs::path rgbDir;
  fs::path plyDir;
  fs::path metadataDir;
  std::size_t groupIndex{0U};
  ImageRecord labels;
  std::optional<ImageRecord> colored;
  ImageRecord rgb;
  PclRecord pcl;
};

struct SaveResult
{
  bool success{false};
  std::string error;
};

namespace
{
std::string JsonEscape(const std::string &value)
{
  std::ostringstream out;
  for (const char ch : value)
  {
    switch (ch)
    {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (static_cast<unsigned char>(ch) < 0x20)
        {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<int>(static_cast<unsigned char>(ch)) << std::dec;
        }
        else
        {
          out << ch;
        }
    }
  }
  return out.str();
}

void EnsureDir(const fs::path &path)
{
  fs::create_directories(path);
}

std::string FormatFrameName(std::size_t index)
{
  std::ostringstream out;
  out << std::setw(6) << std::setfill('0') << index;
  return out.str();
}

bool WritePpm(const fs::path &path, unsigned int width, unsigned int height,
              const std::vector<unsigned char> &data)
{
  std::ofstream out(path, std::ios::binary);
  if (!out)
    return false;
  out << "P6\n" << width << " " << height << "\n255\n";
  out.write(reinterpret_cast<const char *>(data.data()),
            static_cast<std::streamsize>(data.size()));
  return out.good();
}

bool WritePgm(const fs::path &path, unsigned int width, unsigned int height,
              const std::vector<unsigned char> &data)
{
  std::ofstream out(path, std::ios::binary);
  if (!out)
    return false;
  out << "P5\n" << width << " " << height << "\n255\n";
  out.write(reinterpret_cast<const char *>(data.data()),
            static_cast<std::streamsize>(data.size()));
  return out.good();
}

bool WritePgm16(const fs::path &path, unsigned int width, unsigned int height,
                const std::vector<std::uint16_t> &data)
{
  std::ofstream out(path, std::ios::binary);
  if (!out)
    return false;
  out << "P5\n" << width << " " << height << "\n65535\n";
  for (const std::uint16_t value : data)
  {
    const unsigned char bytes[2] = {
      static_cast<unsigned char>((value >> 8) & 0xFF),
      static_cast<unsigned char>(value & 0xFF),
    };
    out.write(reinterpret_cast<const char *>(bytes), 2);
  }
  return out.good();
}

bool WriteAsciiPly(const fs::path &path, const std::vector<PointRecord> &points)
{
  std::ofstream out(path);
  if (!out)
    return false;
  out << "ply\n";
  out << "format ascii 1.0\n";
  out << "element vertex " << points.size() << "\n";
  out << "property float x\n";
  out << "property float y\n";
  out << "property float z\n";
  out << "property uchar red\n";
  out << "property uchar green\n";
  out << "property uchar blue\n";
  out << "property int pixel_u\n";
  out << "property int pixel_v\n";
  out << "end_header\n";
  out << std::fixed << std::setprecision(6);
  for (const auto &point : points)
  {
    out << point.x << " " << point.y << " " << point.z << " "
        << static_cast<int>(point.r) << " " << static_cast<int>(point.g) << " "
        << static_cast<int>(point.b) << " " << point.pixelU << " " << point.pixelV << "\n";
  }
  return out.good();
}

bool WriteTextFile(const fs::path &path, const std::string &contents)
{
  std::ofstream out(path);
  if (!out)
    return false;
  out << contents;
  return out.good();
}

std::string ImageExtension()
{
  return ".ppm";
}

std::string LabelExtension()
{
  return ".pgm";
}

std::string CountExtension()
{
  return ".pgm";
}

void ParseLabelsOrColoredTopic(const std::string &topic, std::string &cameraId, std::string &mapType)
{
  std::vector<std::string> parts;
  std::stringstream ss(topic);
  std::string item;
  while (std::getline(ss, item, '/'))
  {
    if (!item.empty())
      parts.push_back(item);
  }
  if (parts.size() != 5 || parts[0] != "perception" || parts[1] != "native" ||
      parts[2] != "stable_instance_panoptic" ||
      (parts[4] != "labels_map" && parts[4] != "colored_map"))
  {
    throw std::runtime_error("Unsupported stable-instance panoptic topic shape: " + topic);
  }
  cameraId = parts[3];
  mapType = parts[4];
}

void ParseRgbTopic(const std::string &topic, std::string &cameraId)
{
  std::vector<std::string> parts;
  std::stringstream ss(topic);
  std::string item;
  while (std::getline(ss, item, '/'))
  {
    if (!item.empty())
      parts.push_back(item);
  }
  if (parts.size() != 5 || parts[0] != "perception" || parts[1] != "native" ||
      parts[2] != "rgbd" || parts[4] != "rgb")
  {
    throw std::runtime_error("Unsupported RGB topic shape: " + topic);
  }
  cameraId = parts[3];
}

void ParsePclTopic(const std::string &topic, std::string &cameraId)
{
  std::vector<std::string> parts;
  std::stringstream ss(topic);
  std::string item;
  while (std::getline(ss, item, '/'))
  {
    if (!item.empty())
      parts.push_back(item);
  }
  if (parts.size() != 6 || parts[0] != "perception" || parts[1] != "native" ||
      parts[2] != "rgbd" || parts[4] != "depth" || parts[5] != "points")
  {
    throw std::runtime_error("Unsupported point-cloud topic shape: " + topic);
  }
  cameraId = parts[3];
}

Config ParseArgs(int argc, char **argv)
{
  Config config;
  for (int index = 1; index < argc; ++index)
  {
    const std::string arg = argv[index];
    auto requireValue = [&](const std::string &flag) -> std::string {
      if (index + 1 >= argc)
        throw std::runtime_error("Missing value for " + flag);
      return argv[++index];
    };

    if (arg == "--output-root")
      config.outputRoot = fs::path(requireValue(arg));
    else if (arg == "--labels-topic")
      config.labelsTopics.push_back(requireValue(arg));
    else if (arg == "--colored-topic")
      config.coloredTopics.push_back(requireValue(arg));
    else if (arg == "--rgb-topic")
      config.rgbTopics.push_back(requireValue(arg));
    else if (arg == "--pcl-topic")
      config.pclTopics.push_back(requireValue(arg));
    else if (arg == "--max-groups-per-camera")
      config.maxGroupsPerCamera = static_cast<std::size_t>(std::stoul(requireValue(arg)));
    else if (arg == "--timeout-seconds")
      config.timeoutSeconds = std::stod(requireValue(arg));
    else if (arg == "--stride")
      config.stride = static_cast<std::size_t>(std::stoul(requireValue(arg)));
    else if (arg == "--max-sync-delta-ms")
      config.maxSyncDeltaMs = std::stod(requireValue(arg));
    else if (arg == "--max-buffer-per-stream")
      config.maxBufferPerStream = static_cast<std::size_t>(std::stoul(requireValue(arg)));
    else
      throw std::runtime_error("Unknown argument: " + arg);
  }

  if (config.outputRoot.empty())
    throw std::runtime_error("--output-root is required");
  if (config.labelsTopics.empty() || config.rgbTopics.empty() || config.pclTopics.empty())
    throw std::runtime_error("At least one --labels-topic, --rgb-topic, and --pcl-topic are required");
  if (config.labelsTopics.size() != config.rgbTopics.size() ||
      config.labelsTopics.size() != config.pclTopics.size())
  {
    throw std::runtime_error("Labels, RGB, and PCL topic counts must match");
  }
  if (!config.coloredTopics.empty() && config.coloredTopics.size() != config.labelsTopics.size())
    throw std::runtime_error("Colored topic count must match labels topic count when provided");
  if (config.maxGroupsPerCamera == 0U)
    throw std::runtime_error("--max-groups-per-camera must be positive");
  if (!(config.timeoutSeconds > 0.0))
    throw std::runtime_error("--timeout-seconds must be positive");
  if (config.stride == 0U)
    throw std::runtime_error("--stride must be positive");
  if (!(config.maxSyncDeltaMs >= 0.0))
    throw std::runtime_error("--max-sync-delta-ms must be non-negative");
  if (config.maxBufferPerStream == 0U)
    throw std::runtime_error("--max-buffer-per-stream must be positive");
  return config;
}

std::string DataTypeName(gz::msgs::PointCloudPacked::Field::DataType datatype)
{
  switch (datatype)
  {
    case gz::msgs::PointCloudPacked::Field::INT8: return "INT8";
    case gz::msgs::PointCloudPacked::Field::UINT8: return "UINT8";
    case gz::msgs::PointCloudPacked::Field::INT16: return "INT16";
    case gz::msgs::PointCloudPacked::Field::UINT16: return "UINT16";
    case gz::msgs::PointCloudPacked::Field::INT32: return "INT32";
    case gz::msgs::PointCloudPacked::Field::UINT32: return "UINT32";
    case gz::msgs::PointCloudPacked::Field::FLOAT32: return "FLOAT32";
    case gz::msgs::PointCloudPacked::Field::FLOAT64: return "FLOAT64";
    default: return "UNKNOWN";
  }
}

FieldInfo FindField(const gz::msgs::PointCloudPacked &msg, const std::string &name)
{
  FieldInfo info;
  for (int index = 0; index < msg.field_size(); ++index)
  {
    const auto &field = msg.field(index);
    if (field.name() == name)
    {
      info.present = true;
      info.name = field.name();
      info.offset = field.offset();
      info.datatype = field.datatype();
      return info;
    }
  }
  return info;
}

bool ReadFloat32(const std::string &data, std::size_t offset, float &value)
{
  if (offset + sizeof(float) > data.size())
    return false;
  std::memcpy(&value, data.data() + offset, sizeof(float));
  return true;
}

std::uint32_t ReadUint32(const std::string &data, std::size_t offset)
{
  std::uint32_t value = 0U;
  if (offset + sizeof(std::uint32_t) <= data.size())
    std::memcpy(&value, data.data() + offset, sizeof(std::uint32_t));
  return value;
}

std::size_t BytesPerPixel(const gz::msgs::PixelFormatType pixelFormat)
{
  switch (pixelFormat)
  {
    case gz::msgs::PixelFormatType::RGB_INT8:
    case gz::msgs::PixelFormatType::BGR_INT8:
      return 3U;
    case gz::msgs::PixelFormatType::RGBA_INT8:
    case gz::msgs::PixelFormatType::BGRA_INT8:
    case gz::msgs::PixelFormatType::R_FLOAT32:
      return 4U;
    default:
      return 0U;
  }
}

std::string ExtractHeaderValue(const gz::msgs::Header &header, const std::string &key)
{
  for (int index = 0; index < header.data_size(); ++index)
  {
    const auto &entry = header.data(index);
    if (entry.key() == key && entry.value_size() > 0)
      return entry.value(0);
  }
  return "";
}

std::string HeaderStampString(const gz::msgs::Header &header)
{
  if (!header.has_stamp())
    return "";
  std::ostringstream out;
  out << header.stamp().sec() << "." << std::setw(9) << std::setfill('0')
      << header.stamp().nsec();
  return out.str();
}

double HeaderStampSeconds(const gz::msgs::Header &header, double fallbackSeconds)
{
  if (!header.has_stamp())
    return fallbackSeconds;
  return static_cast<double>(header.stamp().sec()) +
         static_cast<double>(header.stamp().nsec()) / 1e9;
}

SaveResult SaveSynchronizedGroup(const SaveContext &context, const Config &config)
{
  SaveResult result;
  const unsigned int labelsWidth = context.labels.msg.width();
  const unsigned int labelsHeight = context.labels.msg.height();
  const std::string labelsPixelFormat =
      gz::msgs::PixelFormatType_Name(context.labels.msg.pixel_format_type());
  const std::vector<unsigned char> labelsBytes(
      context.labels.msg.data().begin(), context.labels.msg.data().end());
  if (labelsPixelFormat != "RGB_INT8")
  {
    result.error = "Unsupported labels_map pixel format: " + labelsPixelFormat;
    return result;
  }
  if (labelsBytes.size() < static_cast<std::size_t>(labelsWidth) * labelsHeight * 3U)
  {
    result.error = "labels_map payload is smaller than expected RGB image size";
    return result;
  }

  std::vector<unsigned char> coloredBytes;
  std::string coloredPixelFormat;
  if (context.colored.has_value())
  {
    coloredPixelFormat = gz::msgs::PixelFormatType_Name(context.colored->msg.pixel_format_type());
    coloredBytes.assign(context.colored->msg.data().begin(), context.colored->msg.data().end());
    if (coloredPixelFormat != "RGB_INT8")
    {
      result.error = "Unsupported colored_map pixel format: " + coloredPixelFormat;
      return result;
    }
    if (context.colored->msg.width() != labelsWidth || context.colored->msg.height() != labelsHeight)
    {
      result.error = "colored_map dimensions do not match labels_map dimensions";
      return result;
    }
  }

  const unsigned int rgbWidth = context.rgb.msg.width();
  const unsigned int rgbHeight = context.rgb.msg.height();
  const auto rgbPixelFormatEnum = context.rgb.msg.pixel_format_type();
  const std::string rgbPixelFormat = gz::msgs::PixelFormatType_Name(rgbPixelFormatEnum);
  const std::vector<unsigned char> rgbBytes(
      context.rgb.msg.data().begin(), context.rgb.msg.data().end());
  if (rgbPixelFormat != "RGB_INT8")
  {
    result.error = "Unsupported RGB pixel format: " + rgbPixelFormat;
    return result;
  }

  const auto &msg = context.pcl.msg;
  const std::uint32_t width = msg.width();
  const std::uint32_t height = msg.height();
  const std::uint32_t pointStep = msg.point_step();
  const std::uint32_t rowStep = msg.row_step();
  const std::size_t originalPointCount =
      static_cast<std::size_t>(width) * static_cast<std::size_t>(height);

  if (labelsWidth != width || labelsHeight != height)
  {
    result.error = "labels_map dimensions do not match point-cloud dimensions for camera " +
                   context.cameraId;
    return result;
  }
  if (rgbWidth != width || rgbHeight != height)
  {
    result.error = "RGB dimensions do not match point-cloud dimensions for camera " +
                   context.cameraId;
    return result;
  }

  const FieldInfo fieldX = FindField(msg, "x");
  const FieldInfo fieldY = FindField(msg, "y");
  const FieldInfo fieldZ = FindField(msg, "z");
  const FieldInfo fieldRgb = FindField(msg, "rgb");
  if (!fieldX.present || !fieldY.present || !fieldZ.present)
  {
    result.error = "PointCloudPacked message is missing one of x/y/z fields for camera " +
                   context.cameraId;
    return result;
  }
  if (fieldX.datatype != gz::msgs::PointCloudPacked::Field::FLOAT32 ||
      fieldY.datatype != gz::msgs::PointCloudPacked::Field::FLOAT32 ||
      fieldZ.datatype != gz::msgs::PointCloudPacked::Field::FLOAT32)
  {
    result.error = "PointCloudPacked x/y/z fields must be FLOAT32 for camera " + context.cameraId;
    return result;
  }

  std::vector<PointRecord> points;
  points.reserve(originalPointCount / (config.stride * config.stride) + 1U);
  std::vector<unsigned char> compactLabels(width * height, 0U);
  std::vector<std::uint16_t> gazeboCounts(width * height, 0U);
  for (unsigned int y = 0; y < height; ++y)
  {
    for (unsigned int x = 0; x < width; ++x)
    {
      const std::size_t pixelIndex = static_cast<std::size_t>(y) * width + x;
      const std::size_t rgbIndex = pixelIndex * 3U;
      compactLabels[pixelIndex] = labelsBytes[rgbIndex + 2U];
      gazeboCounts[pixelIndex] =
          static_cast<std::uint16_t>(labelsBytes[rgbIndex + 1U]) * 256U +
          static_cast<std::uint16_t>(labelsBytes[rgbIndex]);
    }
  }

  std::size_t sampledPointCount = 0U;
  std::size_t finitePointCount = 0U;
  std::size_t writtenPointCount = 0U;
  std::size_t skippedNonfiniteCount = 0U;
  bool firstPackedRgbCaptured = false;
  std::uint32_t firstPackedRgbValue = 0U;

  for (std::uint32_t v = 0U; v < height; v += static_cast<std::uint32_t>(config.stride))
  {
    for (std::uint32_t u = 0U; u < width; u += static_cast<std::uint32_t>(config.stride))
    {
      const std::size_t pointOffset =
          static_cast<std::size_t>(v) * static_cast<std::size_t>(rowStep) +
          static_cast<std::size_t>(u) * static_cast<std::size_t>(pointStep);
      if (pointOffset + pointStep > static_cast<std::size_t>(msg.data().size()))
        continue;

      ++sampledPointCount;
      float x = 0.0F;
      float y = 0.0F;
      float z = 0.0F;
      if (!ReadFloat32(msg.data(), pointOffset + fieldX.offset, x) ||
          !ReadFloat32(msg.data(), pointOffset + fieldY.offset, y) ||
          !ReadFloat32(msg.data(), pointOffset + fieldZ.offset, z))
      {
        continue;
      }
      if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
      {
        ++skippedNonfiniteCount;
        continue;
      }
      ++finitePointCount;

      PointRecord point;
      point.x = x;
      point.y = y;
      point.z = z;
      point.pixelU = static_cast<int>(u);
      point.pixelV = static_cast<int>(v);
      if (fieldRgb.present &&
          fieldRgb.datatype == gz::msgs::PointCloudPacked::Field::FLOAT32)
      {
        const std::uint32_t packed = ReadUint32(msg.data(), pointOffset + fieldRgb.offset);
        point.r = static_cast<std::uint8_t>((packed >> 16) & 0xFFU);
        point.g = static_cast<std::uint8_t>((packed >> 8) & 0xFFU);
        point.b = static_cast<std::uint8_t>(packed & 0xFFU);
        if (!firstPackedRgbCaptured)
        {
          firstPackedRgbCaptured = true;
          firstPackedRgbValue = packed;
        }
      }
      points.push_back(point);
      ++writtenPointCount;
    }
  }

  const std::string rawPclColorSource =
      (fieldRgb.present && fieldRgb.datatype == gz::msgs::PointCloudPacked::Field::FLOAT32)
          ? "packed_rgb_float32"
          : "none_default_white";

  std::ostringstream fieldNames;
  fieldNames << "[";
  for (int index = 0; index < msg.field_size(); ++index)
  {
    if (index > 0)
      fieldNames << ",";
    fieldNames << "\"" << JsonEscape(msg.field(index).name()) << "\"";
  }
  fieldNames << "]";

  const std::string frameName = FormatFrameName(context.groupIndex);
  const fs::path labelsRgbPath = context.labelsDir / (frameName + ImageExtension());
  const fs::path compactPath = context.compactDir / (frameName + LabelExtension());
  const fs::path gazeboCountPath = context.gazeboCountDir / (frameName + CountExtension());
  const fs::path coloredPath = context.coloredDir / (frameName + ImageExtension());
  const fs::path rgbPath = context.rgbDir / (frameName + ImageExtension());
  const fs::path plyPath = context.plyDir / (frameName + ".ply");
  const fs::path metadataPath = context.metadataDir / ("sync_" + frameName + ".json");

  const fs::path labelsRgbTempPath = context.labelsDir / (frameName + ImageExtension() + ".tmp");
  const fs::path compactTempPath = context.compactDir / (frameName + LabelExtension() + ".tmp");
  const fs::path gazeboCountTempPath = context.gazeboCountDir / (frameName + CountExtension() + ".tmp");
  const fs::path coloredTempPath = context.coloredDir / (frameName + ImageExtension() + ".tmp");
  const fs::path rgbTempPath = context.rgbDir / (frameName + ImageExtension() + ".tmp");
  const fs::path plyTempPath = context.plyDir / (frameName + ".ply.tmp");
  const fs::path metadataTempPath = context.metadataDir / ("sync_" + frameName + ".json.tmp");

  std::error_code cleanupError;
  for (const auto &tempPath :
       {labelsRgbTempPath, compactTempPath, gazeboCountTempPath, coloredTempPath, rgbTempPath, plyTempPath, metadataTempPath})
  {
    fs::remove(tempPath, cleanupError);
  }

  if (!WritePpm(labelsRgbTempPath, labelsWidth, labelsHeight, labelsBytes))
  {
    result.error = "Failed to write temporary labels RGB map: " + labelsRgbTempPath.string();
    return result;
  }
  if (!WritePgm(compactTempPath, labelsWidth, labelsHeight, compactLabels))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    result.error = "Failed to write temporary compact instance label mask: " + compactTempPath.string();
    return result;
  }
  if (!WritePgm16(gazeboCountTempPath, labelsWidth, labelsHeight, gazeboCounts))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    fs::remove(compactTempPath, cleanupError);
    result.error = "Failed to write temporary Gazebo instance count mask: " + gazeboCountTempPath.string();
    return result;
  }
  if (context.colored.has_value() &&
      !WritePpm(coloredTempPath, labelsWidth, labelsHeight, coloredBytes))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    fs::remove(compactTempPath, cleanupError);
    fs::remove(gazeboCountTempPath, cleanupError);
    result.error = "Failed to write temporary colored map: " + coloredTempPath.string();
    return result;
  }
  if (!WritePpm(rgbTempPath, rgbWidth, rgbHeight, rgbBytes))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    fs::remove(compactTempPath, cleanupError);
    fs::remove(gazeboCountTempPath, cleanupError);
    fs::remove(coloredTempPath, cleanupError);
    result.error = "Failed to write temporary synchronized RGB image: " + rgbTempPath.string();
    return result;
  }
  if (!WriteAsciiPly(plyTempPath, points))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    fs::remove(compactTempPath, cleanupError);
    fs::remove(gazeboCountTempPath, cleanupError);
    fs::remove(coloredTempPath, cleanupError);
    fs::remove(rgbTempPath, cleanupError);
    result.error = "Failed to write temporary synchronized PLY file: " + plyTempPath.string();
    return result;
  }

  const double minStamp = std::min(
      {context.labels.stampSeconds, context.rgb.stampSeconds, context.pcl.stampSeconds});
  const double maxStamp = std::max(
      {context.labels.stampSeconds, context.rgb.stampSeconds, context.pcl.stampSeconds});
  const double maxTimeDeltaMs = (maxStamp - minStamp) * 1000.0;

  std::ostringstream metadataContents;
  metadataContents << "{\n";
  metadataContents << "  \"camera_id\": \"" << JsonEscape(context.cameraId) << "\",\n";
  metadataContents << "  \"group_index\": " << context.groupIndex << ",\n";
  metadataContents << "  \"labels_topic\": \"" << JsonEscape(context.labelsTopic) << "\",\n";
  metadataContents << "  \"colored_map_topic\": \"" << JsonEscape(context.coloredTopic) << "\",\n";
  metadataContents << "  \"rgb_topic\": \"" << JsonEscape(context.rgbTopic) << "\",\n";
  metadataContents << "  \"pcl_topic\": \"" << JsonEscape(context.pclTopic) << "\",\n";
  metadataContents << "  \"labels_header_stamp\": \"" << JsonEscape(context.labels.headerStamp) << "\",\n";
  metadataContents << "  \"colored_map_header_stamp\": \""
                   << JsonEscape(context.colored.has_value() ? context.colored->headerStamp : std::string()) << "\",\n";
  metadataContents << "  \"rgb_header_stamp\": \"" << JsonEscape(context.rgb.headerStamp) << "\",\n";
  metadataContents << "  \"pcl_header_stamp\": \"" << JsonEscape(context.pcl.headerStamp) << "\",\n";
  metadataContents << "  \"max_time_delta_ms\": " << std::fixed << std::setprecision(6)
                   << maxTimeDeltaMs << ",\n";
  metadataContents << "  \"labels_rgb_path\": \"" << JsonEscape(fs::absolute(labelsRgbPath).string()) << "\",\n";
  metadataContents << "  \"compact_instance_label_path\": \"" << JsonEscape(fs::absolute(compactPath).string()) << "\",\n";
  metadataContents << "  \"gazebo_instance_count_path\": \"" << JsonEscape(fs::absolute(gazeboCountPath).string()) << "\",\n";
  metadataContents << "  \"colored_map_path\": \"" << JsonEscape(context.colored.has_value() ? fs::absolute(coloredPath).string() : std::string()) << "\",\n";
  metadataContents << "  \"rgb_path\": \"" << JsonEscape(fs::absolute(rgbPath).string()) << "\",\n";
  metadataContents << "  \"pcl_path\": \"" << JsonEscape(fs::absolute(plyPath).string()) << "\",\n";
  metadataContents << "  \"width\": " << width << ",\n";
  metadataContents << "  \"height\": " << height << ",\n";
  metadataContents << "  \"stride\": " << config.stride << ",\n";
  metadataContents << "  \"original_point_count\": " << originalPointCount << ",\n";
  metadataContents << "  \"sampled_point_count\": " << sampledPointCount << ",\n";
  metadataContents << "  \"finite_point_count\": " << finitePointCount << ",\n";
  metadataContents << "  \"written_point_count\": " << writtenPointCount << ",\n";
  metadataContents << "  \"point_count\": " << writtenPointCount << ",\n";
  metadataContents << "  \"skipped_nonfinite_count\": " << skippedNonfiniteCount << ",\n";
  metadataContents << "  \"has_pixel_coordinates\": true,\n";
  metadataContents << "  \"label_mode\": \"compact_stable_instance\",\n";
  metadataContents << "  \"color_source\": \"raw_direct_pcl_rgb\",\n";
  metadataContents << "  \"raw_pcl_color_source\": \"" << JsonEscape(rawPclColorSource) << "\",\n";
  metadataContents << "  \"labels_pixel_format_type\": \"" << JsonEscape(labelsPixelFormat) << "\",\n";
  metadataContents << "  \"rgb_pixel_format_type\": \"" << JsonEscape(rgbPixelFormat) << "\",\n";
  metadataContents << "  \"rgb_bytes_per_pixel\": " << BytesPerPixel(rgbPixelFormatEnum) << ",\n";
  metadataContents << "  \"point_step\": " << pointStep << ",\n";
  metadataContents << "  \"row_step\": " << rowStep << ",\n";
  metadataContents << "  \"field_names\": " << fieldNames.str() << ",\n";
  metadataContents << "  \"frame_id\": \"" << JsonEscape(ExtractHeaderValue(msg.header(), "frame_id")) << "\",\n";
  if (firstPackedRgbCaptured)
  {
    std::ostringstream rgbHex;
    rgbHex << "0x" << std::hex << std::setw(8) << std::setfill('0') << firstPackedRgbValue;
    metadataContents << "  \"packed_rgb_hex_first_valid\": \"" << rgbHex.str() << "\"\n";
  }
  else
  {
    metadataContents << "  \"packed_rgb_hex_first_valid\": \"\"\n";
  }
  metadataContents << "}\n";

  if (!WriteTextFile(metadataTempPath, metadataContents.str()))
  {
    fs::remove(labelsRgbTempPath, cleanupError);
    fs::remove(compactTempPath, cleanupError);
    fs::remove(gazeboCountTempPath, cleanupError);
    fs::remove(coloredTempPath, cleanupError);
    fs::remove(rgbTempPath, cleanupError);
    fs::remove(plyTempPath, cleanupError);
    result.error = "Failed to write temporary synchronized metadata JSON: " +
                   metadataTempPath.string();
    return result;
  }

  std::error_code renameError;
  fs::rename(labelsRgbTempPath, labelsRgbPath, renameError);
  if (renameError)
  {
    result.error = "Failed to rename labels RGB map into place: " + renameError.message();
    return result;
  }
  fs::rename(compactTempPath, compactPath, renameError);
  if (renameError)
  {
    fs::remove(labelsRgbPath, cleanupError);
    result.error = "Failed to rename compact label mask into place: " + renameError.message();
    return result;
  }
  fs::rename(gazeboCountTempPath, gazeboCountPath, renameError);
  if (renameError)
  {
    fs::remove(labelsRgbPath, cleanupError);
    fs::remove(compactPath, cleanupError);
    result.error = "Failed to rename Gazebo instance count mask into place: " + renameError.message();
    return result;
  }
  if (context.colored.has_value())
  {
    fs::rename(coloredTempPath, coloredPath, renameError);
    if (renameError)
    {
      fs::remove(labelsRgbPath, cleanupError);
      fs::remove(compactPath, cleanupError);
      fs::remove(gazeboCountPath, cleanupError);
      result.error = "Failed to rename colored map into place: " + renameError.message();
      return result;
    }
  }
  fs::rename(rgbTempPath, rgbPath, renameError);
  if (renameError)
  {
    fs::remove(labelsRgbPath, cleanupError);
    fs::remove(compactPath, cleanupError);
    fs::remove(gazeboCountPath, cleanupError);
    fs::remove(coloredPath, cleanupError);
    result.error = "Failed to rename synchronized RGB image into place: " + renameError.message();
    return result;
  }
  fs::rename(plyTempPath, plyPath, renameError);
  if (renameError)
  {
    fs::remove(labelsRgbPath, cleanupError);
    fs::remove(compactPath, cleanupError);
    fs::remove(gazeboCountPath, cleanupError);
    fs::remove(coloredPath, cleanupError);
    fs::remove(rgbPath, cleanupError);
    result.error = "Failed to rename synchronized PLY into place: " + renameError.message();
    return result;
  }
  fs::rename(metadataTempPath, metadataPath, renameError);
  if (renameError)
  {
    fs::remove(labelsRgbPath, cleanupError);
    fs::remove(compactPath, cleanupError);
    fs::remove(gazeboCountPath, cleanupError);
    fs::remove(coloredPath, cleanupError);
    fs::remove(rgbPath, cleanupError);
    fs::remove(plyPath, cleanupError);
    result.error = "Failed to rename synchronized metadata into place: " + renameError.message();
    return result;
  }

  result.success = true;
  return result;
}
}  // namespace

int main(int argc, char **argv)
{
  try
  {
    const Config config = ParseArgs(argc, argv);
    gz::transport::Node node;
    std::mutex stateMutex;
    std::mutex errorMutex;
    std::map<std::string, CameraState> cameras;
    std::map<std::string, std::string> labelsTopicToCamera;
    std::map<std::string, std::string> coloredTopicToCamera;
    std::map<std::string, std::string> rgbTopicToCamera;
    std::map<std::string, std::string> pclTopicToCamera;
    std::atomic<bool> anyMessage{false};
    std::atomic<std::size_t> failedWriteCount{0U};
    std::vector<std::string> writeErrors;
    const auto timeOrigin = std::chrono::steady_clock::now();

    for (std::size_t index = 0; index < config.labelsTopics.size(); ++index)
    {
      std::string labelsCameraId;
      std::string labelsMapType;
      ParseLabelsOrColoredTopic(config.labelsTopics[index], labelsCameraId, labelsMapType);
      if (labelsMapType != "labels_map")
        throw std::runtime_error("labels topic must end with /labels_map");

      std::string coloredCameraId = labelsCameraId;
      if (!config.coloredTopics.empty())
      {
        std::string coloredMapType;
        ParseLabelsOrColoredTopic(config.coloredTopics[index], coloredCameraId, coloredMapType);
        if (coloredMapType != "colored_map")
          throw std::runtime_error("colored topic must end with /colored_map");
      }

      std::string rgbCameraId;
      std::string pclCameraId;
      ParseRgbTopic(config.rgbTopics[index], rgbCameraId);
      ParsePclTopic(config.pclTopics[index], pclCameraId);
      if (labelsCameraId != coloredCameraId || labelsCameraId != rgbCameraId || labelsCameraId != pclCameraId)
      {
        throw std::runtime_error("Topic camera ID mismatch at index " + std::to_string(index));
      }

      CameraState state;
      state.cameraId = labelsCameraId;
      state.labelsTopic = config.labelsTopics[index];
      state.coloredTopic = config.coloredTopics.empty() ? "" : config.coloredTopics[index];
      state.rgbTopic = config.rgbTopics[index];
      state.pclTopic = config.pclTopics[index];
      state.rootDir = config.outputRoot / state.cameraId;
      state.labelsDir = state.rootDir / "labels_maps_rgb";
      state.compactDir = state.rootDir / "compact_instance_label";
      state.gazeboCountDir = state.rootDir / "gazebo_instance_count";
      state.coloredDir = state.rootDir / "colored_maps";
      state.rgbDir = state.rootDir / "rgb";
      state.plyDir = state.rootDir / "ply";
      state.metadataDir = state.rootDir / "metadata";
      EnsureDir(state.labelsDir);
      EnsureDir(state.compactDir);
      EnsureDir(state.gazeboCountDir);
      EnsureDir(state.coloredDir);
      EnsureDir(state.rgbDir);
      EnsureDir(state.plyDir);
      EnsureDir(state.metadataDir);
      cameras.emplace(state.cameraId, state);
      labelsTopicToCamera.emplace(state.labelsTopic, state.cameraId);
      if (!state.coloredTopic.empty())
        coloredTopicToCamera.emplace(state.coloredTopic, state.cameraId);
      rgbTopicToCamera.emplace(state.rgbTopic, state.cameraId);
      pclTopicToCamera.emplace(state.pclTopic, state.cameraId);
    }

    auto attemptGroup = [&](const std::string &cameraId) {
      while (true)
      {
        std::optional<SaveContext> saveContext;
        {
          std::lock_guard<std::mutex> lock(stateMutex);
          auto found = cameras.find(cameraId);
          if (found == cameras.end())
            return;
          auto &state = found->second;
          if (state.count + state.pendingSaveCount >= config.maxGroupsPerCamera)
            return;
          if (state.pendingLabels.empty() || state.pendingRgb.empty() || state.pendingPcl.empty())
            return;

          double bestSpanMs = std::numeric_limits<double>::infinity();
          std::size_t bestLabels = 0U;
          std::size_t bestRgb = 0U;
          std::size_t bestPcl = 0U;
          bool foundGroup = false;
          for (std::size_t labelsIndex = 0U; labelsIndex < state.pendingLabels.size(); ++labelsIndex)
          {
            for (std::size_t rgbIndex = 0U; rgbIndex < state.pendingRgb.size(); ++rgbIndex)
            {
              for (std::size_t pclIndex = 0U; pclIndex < state.pendingPcl.size(); ++pclIndex)
              {
                const double minStamp = std::min(
                    {state.pendingLabels[labelsIndex].stampSeconds,
                     state.pendingRgb[rgbIndex].stampSeconds,
                     state.pendingPcl[pclIndex].stampSeconds});
                const double maxStamp = std::max(
                    {state.pendingLabels[labelsIndex].stampSeconds,
                     state.pendingRgb[rgbIndex].stampSeconds,
                     state.pendingPcl[pclIndex].stampSeconds});
                const double spanMs = (maxStamp - minStamp) * 1000.0;
                if (spanMs < bestSpanMs)
                {
                  bestSpanMs = spanMs;
                  bestLabels = labelsIndex;
                  bestRgb = rgbIndex;
                  bestPcl = pclIndex;
                  foundGroup = true;
                }
              }
            }
          }
          if (!foundGroup || bestSpanMs > config.maxSyncDeltaMs)
            return;

          std::optional<std::size_t> bestColored;
          double bestColoredDeltaMs = std::numeric_limits<double>::infinity();
          for (std::size_t coloredIndex = 0U; coloredIndex < state.pendingColored.size(); ++coloredIndex)
          {
            const double deltaMs = std::abs(
                state.pendingColored[coloredIndex].stampSeconds -
                state.pendingLabels[bestLabels].stampSeconds) * 1000.0;
            if (deltaMs <= config.maxSyncDeltaMs && deltaMs < bestColoredDeltaMs)
            {
              bestColored = coloredIndex;
              bestColoredDeltaMs = deltaMs;
            }
          }

          saveContext = SaveContext{
              state.cameraId,
              state.labelsTopic,
              state.coloredTopic,
              state.rgbTopic,
              state.pclTopic,
              state.labelsDir,
              state.compactDir,
              state.gazeboCountDir,
              state.coloredDir,
              state.rgbDir,
              state.plyDir,
              state.metadataDir,
              state.nextGroupIndex++,
              state.pendingLabels[bestLabels],
              bestColored.has_value() ? std::optional<ImageRecord>(state.pendingColored[*bestColored]) : std::nullopt,
              state.pendingRgb[bestRgb],
              state.pendingPcl[bestPcl],
          };
          state.pendingLabels.erase(state.pendingLabels.begin() + static_cast<long>(bestLabels));
          state.pendingRgb.erase(state.pendingRgb.begin() + static_cast<long>(bestRgb));
          state.pendingPcl.erase(state.pendingPcl.begin() + static_cast<long>(bestPcl));
          if (bestColored.has_value())
            state.pendingColored.erase(state.pendingColored.begin() + static_cast<long>(*bestColored));
          ++state.pendingSaveCount;
        }

        const SaveResult saveResult = SaveSynchronizedGroup(*saveContext, config);
        {
          std::lock_guard<std::mutex> lock(stateMutex);
          auto found = cameras.find(cameraId);
          if (found != cameras.end())
          {
            if (found->second.pendingSaveCount > 0U)
              --found->second.pendingSaveCount;
            if (saveResult.success)
              ++found->second.count;
          }
        }
        if (!saveResult.success)
        {
          failedWriteCount.fetch_add(1U);
          std::lock_guard<std::mutex> lock(errorMutex);
          writeErrors.push_back(saveResult.error);
        }
      }
    };

    auto nowSeconds = [&]() -> double {
      return std::chrono::duration_cast<std::chrono::duration<double>>(
                 std::chrono::steady_clock::now() - timeOrigin)
          .count();
    };

    auto pushImageRecord = [&](const std::string &cameraId,
                               std::vector<ImageRecord> CameraState::*pendingField,
                               const gz::msgs::Image &msg) {
      ImageRecord record;
      record.msg = msg;
      record.headerStamp = HeaderStampString(msg.header());
      record.stampSeconds = HeaderStampSeconds(msg.header(), nowSeconds());
      {
        std::lock_guard<std::mutex> lock(stateMutex);
        auto cameraFound = cameras.find(cameraId);
        if (cameraFound == cameras.end())
          return;
        auto &pending = cameraFound->second.*pendingField;
        pending.push_back(record);
        if (pending.size() > config.maxBufferPerStream)
          pending.erase(pending.begin(), pending.begin() + static_cast<long>(pending.size() - config.maxBufferPerStream));
      }
      attemptGroup(cameraId);
    };

    auto handleLabelsMessage = [&](const std::string &topic, const gz::msgs::Image &msg) {
      anyMessage.store(true);
      const auto found = labelsTopicToCamera.find(topic);
      if (found == labelsTopicToCamera.end())
        return;
      pushImageRecord(found->second, &CameraState::pendingLabels, msg);
    };

    auto handleColoredMessage = [&](const std::string &topic, const gz::msgs::Image &msg) {
      anyMessage.store(true);
      const auto found = coloredTopicToCamera.find(topic);
      if (found == coloredTopicToCamera.end())
        return;
      pushImageRecord(found->second, &CameraState::pendingColored, msg);
    };

    auto handleRgbMessage = [&](const std::string &topic, const gz::msgs::Image &msg) {
      anyMessage.store(true);
      const auto found = rgbTopicToCamera.find(topic);
      if (found == rgbTopicToCamera.end())
        return;
      pushImageRecord(found->second, &CameraState::pendingRgb, msg);
    };

    auto handlePclMessage = [&](const std::string &topic, const gz::msgs::PointCloudPacked &msg) {
      anyMessage.store(true);
      const auto found = pclTopicToCamera.find(topic);
      if (found == pclTopicToCamera.end())
        return;
      const std::string &cameraId = found->second;
      PclRecord record;
      record.msg = msg;
      record.headerStamp = HeaderStampString(msg.header());
      record.stampSeconds = HeaderStampSeconds(msg.header(), nowSeconds());
      {
        std::lock_guard<std::mutex> lock(stateMutex);
        auto cameraFound = cameras.find(cameraId);
        if (cameraFound == cameras.end())
          return;
        auto &pending = cameraFound->second.pendingPcl;
        pending.push_back(record);
        if (pending.size() > config.maxBufferPerStream)
          pending.erase(pending.begin(), pending.begin() + static_cast<long>(pending.size() - config.maxBufferPerStream));
      }
      attemptGroup(cameraId);
    };

    std::vector<std::function<void(const gz::msgs::Image &)>> imageCallbacks;
    std::vector<std::function<void(const gz::msgs::PointCloudPacked &)>> pclCallbacks;
    imageCallbacks.reserve(labelsTopicToCamera.size() + coloredTopicToCamera.size() + rgbTopicToCamera.size());
    pclCallbacks.reserve(pclTopicToCamera.size());

    for (const auto &[topic, cameraId] : labelsTopicToCamera)
    {
      std::function<void(const gz::msgs::Image &)> callback =
          [topic, &handleLabelsMessage](const gz::msgs::Image &msg) { handleLabelsMessage(topic, msg); };
      imageCallbacks.push_back(callback);
      if (!node.Subscribe(topic, imageCallbacks.back()))
        throw std::runtime_error("Failed to subscribe to labels topic: " + topic);
    }
    for (const auto &[topic, cameraId] : coloredTopicToCamera)
    {
      std::function<void(const gz::msgs::Image &)> callback =
          [topic, &handleColoredMessage](const gz::msgs::Image &msg) { handleColoredMessage(topic, msg); };
      imageCallbacks.push_back(callback);
      if (!node.Subscribe(topic, imageCallbacks.back()))
        throw std::runtime_error("Failed to subscribe to colored topic: " + topic);
    }
    for (const auto &[topic, cameraId] : rgbTopicToCamera)
    {
      std::function<void(const gz::msgs::Image &)> callback =
          [topic, &handleRgbMessage](const gz::msgs::Image &msg) { handleRgbMessage(topic, msg); };
      imageCallbacks.push_back(callback);
      if (!node.Subscribe(topic, imageCallbacks.back()))
        throw std::runtime_error("Failed to subscribe to RGB topic: " + topic);
    }
    for (const auto &[topic, cameraId] : pclTopicToCamera)
    {
      std::function<void(const gz::msgs::PointCloudPacked &)> callback =
          [topic, &handlePclMessage](const gz::msgs::PointCloudPacked &msg) { handlePclMessage(topic, msg); };
      pclCallbacks.push_back(callback);
      if (!node.Subscribe(topic, pclCallbacks.back()))
        throw std::runtime_error("Failed to subscribe to PCL topic: " + topic);
    }

    const auto deadline = std::chrono::steady_clock::now() +
        std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::duration<double>(config.timeoutSeconds));

    while (std::chrono::steady_clock::now() < deadline)
    {
      bool allComplete = true;
      {
        std::lock_guard<std::mutex> lock(stateMutex);
        for (const auto &[cameraId, state] : cameras)
        {
          if (state.count < config.maxGroupsPerCamera)
          {
            allComplete = false;
            break;
          }
        }
      }
      if (allComplete)
        break;
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    std::lock_guard<std::mutex> lock(stateMutex);
    std::cout << "{\n";
    std::cout << "  \"mode\": \"sync_stable_instance_rgb_pcl\",\n";
    std::cout << "  \"topic_count\": "
              << (labelsTopicToCamera.size() + coloredTopicToCamera.size() + rgbTopicToCamera.size() + pclTopicToCamera.size())
              << ",\n";
    std::cout << "  \"camera_count\": " << cameras.size() << ",\n";
    std::cout << "  \"max_groups_per_camera\": " << config.maxGroupsPerCamera << ",\n";
    std::cout << "  \"timeout_seconds\": " << config.timeoutSeconds << ",\n";
    std::cout << "  \"stride\": " << config.stride << ",\n";
    std::cout << "  \"max_sync_delta_ms\": " << config.maxSyncDeltaMs << ",\n";
    std::cout << "  \"any_message_received\": " << (anyMessage.load() ? "true" : "false") << ",\n";
    std::cout << "  \"failed_write_count\": " << failedWriteCount.load() << ",\n";
    std::cout << "  \"write_errors\": [";
    for (std::size_t index = 0; index < writeErrors.size(); ++index)
    {
      if (index > 0)
        std::cout << ", ";
      std::cout << "\"" << JsonEscape(writeErrors[index]) << "\"";
    }
    std::cout << "],\n";
    std::cout << "  \"topics\": [\n";
    bool first = true;
    for (const auto &[cameraId, state] : cameras)
    {
      if (!first)
        std::cout << ",\n";
      first = false;
      std::cout << "    {\n";
      std::cout << "      \"camera_id\": \"" << JsonEscape(cameraId) << "\",\n";
      std::cout << "      \"labels_topic\": \"" << JsonEscape(state.labelsTopic) << "\",\n";
      std::cout << "      \"colored_topic\": \"" << JsonEscape(state.coloredTopic) << "\",\n";
      std::cout << "      \"rgb_topic\": \"" << JsonEscape(state.rgbTopic) << "\",\n";
      std::cout << "      \"pcl_topic\": \"" << JsonEscape(state.pclTopic) << "\",\n";
      std::cout << "      \"group_count\": " << state.count << "\n";
      std::cout << "    }";
    }
    std::cout << "\n  ]\n";
    std::cout << "}\n";
    return 0;
  }
  catch (const std::exception &exc)
  {
    std::cerr << "ERROR: " << exc.what() << std::endl;
    return 1;
  }
}
