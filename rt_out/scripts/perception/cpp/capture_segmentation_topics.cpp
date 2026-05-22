#include <gz/msgs/image.pb.h>
#include <gz/transport/Node.hh>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef HAVE_OPENCV4
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>
#endif

namespace fs = std::filesystem;

struct TopicState
{
  std::string topic;
  std::string mode;
  std::string cameraId;
  std::string mapType;
  fs::path rootDir;
  fs::path mapsDir;
  fs::path decodedDir;
  fs::path semanticDecodedDir;
  fs::path gazeboInstanceCountDir;
  fs::path metadataDir;
  std::size_t count{0};
};

struct Config
{
  std::string mode;
  fs::path outputRoot;
  std::vector<std::string> topics;
  std::size_t maxMessagesPerTopic{5};
  double timeoutSeconds{30.0};
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

std::string FormatFrameName(std::size_t index)
{
  std::ostringstream out;
  out << std::setw(6) << std::setfill('0') << index;
  return out.str();
}

bool SaveRgbImage(const fs::path &path, unsigned int width, unsigned int height,
                  const std::vector<unsigned char> &data)
{
#ifdef HAVE_OPENCV4
  cv::Mat rgb(static_cast<int>(height), static_cast<int>(width), CV_8UC3,
              const_cast<unsigned char *>(data.data()));
  cv::Mat bgr;
  cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
  return cv::imwrite(path.string(), bgr);
#else
  return WritePpm(path, width, height, data);
#endif
}

bool SaveLabelImage(const fs::path &path, unsigned int width, unsigned int height,
                    const std::vector<unsigned char> &data)
{
#ifdef HAVE_OPENCV4
  cv::Mat gray(static_cast<int>(height), static_cast<int>(width), CV_8UC1,
               const_cast<unsigned char *>(data.data()));
  return cv::imwrite(path.string(), gray);
#else
  return WritePgm(path, width, height, data);
#endif
}

bool SaveCountImage(const fs::path &path, unsigned int width, unsigned int height,
                    const std::vector<std::uint16_t> &data)
{
  return WritePgm16(path, width, height, data);
}

std::string ImageExtension()
{
#ifdef HAVE_OPENCV4
  return ".png";
#else
  return ".ppm";
#endif
}

std::string LabelExtension()
{
#ifdef HAVE_OPENCV4
  return ".png";
#else
  return ".pgm";
#endif
}

std::string CountExtension()
{
  return ".pgm";
}

void EnsureDir(const fs::path &path)
{
  fs::create_directories(path);
}

void ParseTopic(const std::string &topic, std::string &mode, std::string &cameraId,
                std::string &mapType)
{
  std::vector<std::string> parts;
  std::stringstream ss(topic);
  std::string item;
  while (std::getline(ss, item, '/'))
  {
    if (!item.empty())
      parts.push_back(item);
  }
  if (parts.size() < 5 || parts[0] != "perception" || parts[1] != "native")
  {
    throw std::runtime_error("Unsupported topic shape: " + topic);
  }
  mode = parts[2];
  cameraId = parts[3];
  mapType = parts[4];
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

    if (arg == "--mode")
      config.mode = requireValue(arg);
    else if (arg == "--output-root")
      config.outputRoot = fs::path(requireValue(arg));
    else if (arg == "--topic")
      config.topics.push_back(requireValue(arg));
    else if (arg == "--max-messages-per-topic")
      config.maxMessagesPerTopic = static_cast<std::size_t>(std::stoul(requireValue(arg)));
    else if (arg == "--timeout-seconds")
      config.timeoutSeconds = std::stod(requireValue(arg));
    else
      throw std::runtime_error("Unknown argument: " + arg);
  }

  if (config.mode.empty())
    throw std::runtime_error("--mode is required");
  if (config.outputRoot.empty())
    throw std::runtime_error("--output-root is required");
  if (config.topics.empty())
    throw std::runtime_error("At least one --topic is required");
  if (config.maxMessagesPerTopic == 0)
    throw std::runtime_error("--max-messages-per-topic must be positive");
  if (!(config.timeoutSeconds > 0.0))
    throw std::runtime_error("--timeout-seconds must be positive");
  return config;
}
}  // namespace

int main(int argc, char **argv)
{
  try
  {
    const Config config = ParseArgs(argc, argv);
    gz::transport::Node node;
    std::mutex stateMutex;
    std::map<std::string, TopicState> states;
    std::atomic<bool> anyMessage{false};

    for (const auto &topic : config.topics)
    {
      TopicState state;
      state.topic = topic;
      ParseTopic(topic, state.mode, state.cameraId, state.mapType);
      state.rootDir = config.outputRoot / state.cameraId;
      if (state.mapType == "labels_map")
      {
        if (state.mode == "panoptic")
        {
          state.mapsDir = state.rootDir / "labels_maps_rgb";
          state.semanticDecodedDir = state.rootDir / "semantic_decoded";
          state.gazeboInstanceCountDir = state.rootDir / "gazebo_instance_count";
        }
        else
        {
          state.mapsDir = state.rootDir / "labels_maps";
          state.decodedDir = state.rootDir / "labels_maps_decoded";
        }
      }
      else
      {
        state.mapsDir = state.rootDir / "colored_maps";
      }
      state.metadataDir = state.rootDir / "metadata";
      EnsureDir(state.mapsDir);
      if (state.mapType == "labels_map")
      {
        if (state.mode == "panoptic")
        {
          EnsureDir(state.semanticDecodedDir);
          EnsureDir(state.gazeboInstanceCountDir);
        }
        else
        {
          EnsureDir(state.decodedDir);
        }
      }
      EnsureDir(state.metadataDir);
      states.emplace(topic, state);
    }

    auto handleImageMessage = [&](const std::string &topic, const gz::msgs::Image &msg) {
      std::size_t messageIndex = 0;
      TopicState stateCopy;
      {
        std::lock_guard<std::mutex> lock(stateMutex);
        auto found = states.find(topic);
        if (found == states.end())
          return;
        if (found->second.count >= config.maxMessagesPerTopic)
          return;
        messageIndex = found->second.count++;
        stateCopy = found->second;
      }

      anyMessage.store(true);
      const unsigned int width = msg.width();
      const unsigned int height = msg.height();
      const std::string pixelFormat = gz::msgs::PixelFormatType_Name(msg.pixel_format_type());
      const std::string frameName = FormatFrameName(messageIndex);
      const std::string rawExt = ImageExtension();
      const std::string labelExt = LabelExtension();
      const std::string countExt = CountExtension();
      const fs::path rawPath = stateCopy.mapsDir / (frameName + rawExt);
      const fs::path metadataPath = stateCopy.metadataDir / (frameName + ".json");

      const std::string dataString = msg.data();
      const std::vector<unsigned char> rawBytes(dataString.begin(), dataString.end());
      bool rawSaved = SaveRgbImage(rawPath, width, height, rawBytes);

      std::string decodedLabelPathString;
      std::string semanticDecodedPathString;
      std::string gazeboInstanceCountPathString;
      if (stateCopy.mapType == "labels_map" && rawBytes.size() >= static_cast<std::size_t>(width) * height * 3)
      {
        if (stateCopy.mode == "panoptic")
        {
          std::vector<unsigned char> semanticDecoded(width * height, 0U);
          std::vector<std::uint16_t> gazeboInstanceCount(width * height, 0U);
          for (unsigned int y = 0; y < height; ++y)
          {
            for (unsigned int x = 0; x < width; ++x)
            {
              const std::size_t pixelIndex = static_cast<std::size_t>(y) * width + x;
              const std::size_t rgbIndex = pixelIndex * 3;
              semanticDecoded[pixelIndex] = rawBytes[rgbIndex + 2];
              gazeboInstanceCount[pixelIndex] =
                static_cast<std::uint16_t>(rawBytes[rgbIndex + 1]) * 256U +
                static_cast<std::uint16_t>(rawBytes[rgbIndex]);
            }
          }
          const fs::path semanticDecodedPath = stateCopy.semanticDecodedDir / (frameName + labelExt);
          if (SaveLabelImage(semanticDecodedPath, width, height, semanticDecoded))
          {
            decodedLabelPathString = semanticDecodedPath.string();
            semanticDecodedPathString = semanticDecodedPath.string();
          }
          const fs::path gazeboInstanceCountPath = stateCopy.gazeboInstanceCountDir / (frameName + countExt);
          if (SaveCountImage(gazeboInstanceCountPath, width, height, gazeboInstanceCount))
            gazeboInstanceCountPathString = gazeboInstanceCountPath.string();
        }
        else
        {
          std::vector<unsigned char> decoded(width * height, 0U);
          for (unsigned int y = 0; y < height; ++y)
          {
            for (unsigned int x = 0; x < width; ++x)
            {
              const std::size_t rgbIndex = (static_cast<std::size_t>(y) * width + x) * 3;
              decoded[static_cast<std::size_t>(y) * width + x] = rawBytes[rgbIndex + 2];
            }
          }
          const fs::path decodedPath = stateCopy.decodedDir / (frameName + labelExt);
          if (SaveLabelImage(decodedPath, width, height, decoded))
            decodedLabelPathString = decodedPath.string();
        }
      }

      std::ofstream meta(metadataPath);
      meta << "{\n";
      meta << "  \"topic\": \"" << JsonEscape(topic) << "\",\n";
      meta << "  \"mode\": \"" << JsonEscape(stateCopy.mode) << "\",\n";
      meta << "  \"camera_id\": \"" << JsonEscape(stateCopy.cameraId) << "\",\n";
      meta << "  \"map_type\": \"" << JsonEscape(stateCopy.mapType) << "\",\n";
      meta << "  \"width\": " << width << ",\n";
      meta << "  \"height\": " << height << ",\n";
      meta << "  \"pixel_format_type\": \"" << JsonEscape(pixelFormat) << "\",\n";
      meta << "  \"data_size\": " << rawBytes.size() << ",\n";
      meta << "  \"saved_raw_rgb_path\": \"" << JsonEscape(rawSaved ? rawPath.string() : std::string()) << "\",\n";
      if (stateCopy.mapType == "labels_map")
      {
        meta << "  \"saved_decoded_label_path\": \"" << JsonEscape(decodedLabelPathString) << "\",\n";
        meta << "  \"saved_semantic_decoded_path\": \"" << JsonEscape(semanticDecodedPathString) << "\",\n";
        meta << "  \"saved_gazebo_instance_count_path\": \"" << JsonEscape(gazeboInstanceCountPathString) << "\",\n";
        if (stateCopy.mode == "panoptic")
        {
          meta << "  \"semantic_label_channel\": 2,\n";
          meta << "  \"instance_count_high_channel\": 1,\n";
          meta << "  \"instance_count_low_channel\": 0,\n";
          meta << "  \"gazebo_instance_count_encoding\": \"rgb[1] * 256 + rgb[0]\",\n";
          meta << "  \"gazebo_instance_count_is_stable_instance_id\": false,\n";
        }
        else
        {
          meta << "  \"semantic_label_channel\": null,\n";
          meta << "  \"instance_count_high_channel\": null,\n";
          meta << "  \"instance_count_low_channel\": null,\n";
          meta << "  \"gazebo_instance_count_encoding\": \"\",\n";
          meta << "  \"gazebo_instance_count_is_stable_instance_id\": null,\n";
        }
      }
      else
      {
        meta << "  \"saved_decoded_label_path\": \"\",\n";
        meta << "  \"saved_semantic_decoded_path\": \"\",\n";
        meta << "  \"saved_gazebo_instance_count_path\": \"\",\n";
        meta << "  \"semantic_label_channel\": null,\n";
        meta << "  \"instance_count_high_channel\": null,\n";
        meta << "  \"instance_count_low_channel\": null,\n";
        meta << "  \"gazebo_instance_count_encoding\": \"\",\n";
        meta << "  \"gazebo_instance_count_is_stable_instance_id\": null,\n";
      }
      meta << "  \"message_index\": " << messageIndex << "\n";
      meta << "}\n";
    };

    std::vector<std::function<void(const gz::msgs::Image &)>> callbacks;
    callbacks.reserve(states.size());
    for (const auto &[topic, state] : states)
    {
      std::function<void(const gz::msgs::Image &)> callback =
        [topic, &handleImageMessage](const gz::msgs::Image &msg)
        {
          handleImageMessage(topic, msg);
        };
      callbacks.push_back(callback);
      if (!node.Subscribe(topic, callbacks.back()))
        throw std::runtime_error("Failed to subscribe to topic: " + topic);
    }

    const auto deadline = std::chrono::steady_clock::now() +
      std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(config.timeoutSeconds));

    while (std::chrono::steady_clock::now() < deadline)
    {
      bool allComplete = true;
      {
        std::lock_guard<std::mutex> lock(stateMutex);
        for (const auto &[topic, state] : states)
        {
          if (state.count < config.maxMessagesPerTopic)
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
    std::cout << "  \"mode\": \"" << JsonEscape(config.mode) << "\",\n";
    std::cout << "  \"topic_count\": " << states.size() << ",\n";
    std::cout << "  \"max_messages_per_topic\": " << config.maxMessagesPerTopic << ",\n";
    std::cout << "  \"timeout_seconds\": " << config.timeoutSeconds << ",\n";
    std::cout << "  \"any_message_received\": " << (anyMessage.load() ? "true" : "false") << ",\n";
    std::cout << "  \"topics\": [\n";
    bool first = true;
    for (const auto &[topic, state] : states)
    {
      if (!first)
        std::cout << ",\n";
      first = false;
      std::cout << "    {\n";
      std::cout << "      \"topic\": \"" << JsonEscape(topic) << "\",\n";
      std::cout << "      \"camera_id\": \"" << JsonEscape(state.cameraId) << "\",\n";
      std::cout << "      \"map_type\": \"" << JsonEscape(state.mapType) << "\",\n";
      std::cout << "      \"message_count\": " << state.count << "\n";
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
