// Copyright (c) 2017 Proyectos y Sistemas de Mantenimiento SL (eProsima).
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include <nlohmann/json.hpp>
#include <pybind11/pybind11.h>

// #define PYBIND11_JSON_DEBUG

#ifdef PYBIND11_JSON_DEBUG
#include <iostream>
#define PYBIND11_JSON_PRINT_DEBUG(msg) std::cout << msg << std::endl;
#else
#define PYBIND11_JSON_PRINT_DEBUG(msg)
#endif


namespace pybind11 {
namespace detail {

template <> struct type_caster<nlohmann::json> {
public:
    PYBIND11_TYPE_CASTER(nlohmann::json, const_name("json"));

    bool load(handle src, bool convert) {
        PYBIND11_JSON_PRINT_DEBUG("Trying to load handle " << src.ptr() << " " << convert);
        if (!src) {
            PYBIND11_JSON_PRINT_DEBUG("Source is NULL");
            return false;
        }

        if (PyBytes_Check(src.ptr())) {
            PYBIND11_JSON_PRINT_DEBUG("Trying to load json from bytes");
            // const char *json_str = PyBytes_AsString(src.ptr()); // before python 3.8
            const char *json_str = PyBytes_AS_STRING(src.ptr()); // since python 3.8
            if (!json_str) {
                PYBIND11_JSON_PRINT_DEBUG("Unable to load string from Python bytes");
                PyErr_Clear();
                return false;
            }
            try {
                value = nlohmann::json::parse(json_str);
                return true;
            } catch (const std::exception &e) {
                PYBIND11_JSON_PRINT_DEBUG("Unable to parse Python bytes as json: " << e.what());
                return false;
            }
        }

        return load_internal(src, convert);
    }

    // Clang doesn't like the const_name part of the PYBIND11_TYPE_CASTER macro
    // for nlohmann::json::value_t because it's an enum. Overriding it here.
    // For some reason, this is only a problem on macOS.
    // See: https://github.com/pybind/pybind11/issues/1800
    // And: https://github.com/pybind/pybind11_json/pull/23
#if defined(__APPLE__) && defined(__clang__)
    //PYBIND11_JSON_PRINT_DEBUG("\n\n\n\n\nAPPLE CLANG workaround for name being an enum\n\n\n\n\n\n");
    //static constexpr auto name = const_name("json");
#endif

private:
    bool load_internal(handle src, bool convert) {
        PYBIND11_JSON_PRINT_DEBUG("Trying to load_internal handle " << src.ptr() << " " << convert);

        if (pybind11::isinstance<pybind11::none>(src)) {
             PYBIND11_JSON_PRINT_DEBUG("Loading None as json::value_t::null");
            value = nullptr;
            return true;
        } else if (pybind11::isinstance<pybind11::bool_>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading bool as json::value_t::boolean");
            value = src.cast<bool>();
            return true;
        } else if (pybind11::isinstance<pybind11::int_>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading int as json::value_t::number_integer");
            value = src.cast<nlohmann::json::number_integer_t>();
            return true;
        } else if (pybind11::isinstance<pybind11::float_>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading float as json::value_t::number_float");
            value = src.cast<double>();
            return true;
        } else if (pybind11::isinstance<pybind11::str>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading str as json::value_t::string");
            value = src.cast<std::string>();
            return true;
        } else if (pybind11::isinstance<pybind11::dict>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading dict as json::value_t::object");
            auto d = pybind11::reinterpret_borrow<pybind11::dict>(src);
            value = nlohmann::json::object();
            for (auto item : d) {
                value[pybind11::cast<std::string>(item.first)] = pybind11::cast<nlohmann::json>(item.second);
            }
            return true;
        } else if (pybind11::isinstance<pybind11::list>(src) || pybind11::isinstance<pybind11::tuple>(src)) {
            PYBIND11_JSON_PRINT_DEBUG("Loading list/tuple as json::value_t::array");
            auto l = pybind11::reinterpret_borrow<pybind11::list>(src);
            value = nlohmann::json::array();
            for (auto item : l) {
                value.push_back(pybind11::cast<nlohmann::json>(item));
            }
            return true;
        } else if (convert) { // If convert is true, go through each possible conversion.
            PYBIND11_JSON_PRINT_DEBUG("Trying to load as json string as a fallback");
#ifdef PYBIND11_JSON_ENABLE_FALLBACK
            try {
                value = nlohmann::json::parse(pybind11::str(src).cast<std::string>());
                return true;
            } catch (const std::exception &e) {
                PYBIND11_JSON_PRINT_DEBUG("Unable to parse as json string: " << e.what());
                return false;
            }
#endif
        }
        PYBIND11_JSON_PRINT_DEBUG("Unable to load handle " << src.ptr());
        return false;
    }


public:
    static handle cast(const nlohmann::json& src, return_value_policy /* policy */, handle /* parent */) {
        PYBIND11_JSON_PRINT_DEBUG("Casting json value of type " << src.type_name());
        switch (src.type()) {
            case nlohmann::json::value_t::null:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::null to None");
                return pybind11::none().inc_ref();
            case nlohmann::json::value_t::boolean:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::boolean to bool");
                return pybind11::bool_(src.get<bool>()).inc_ref();
            case nlohmann::json::value_t::number_integer:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::number_integer to int");
                return pybind11::int_(src.get<nlohmann::json::number_integer_t>()).inc_ref();
            case nlohmann::json::value_t::number_unsigned:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::number_unsigned to int");
                return pybind11::int_(src.get<nlohmann::json::number_unsigned_t>()).inc_ref();
            case nlohmann::json::value_t::number_float:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::number_float to float");
                return pybind11::float_(src.get<double>()).inc_ref();
            case nlohmann::json::value_t::string:
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::string to str");
                return pybind11::str(src.get<std::string>()).inc_ref();
            case nlohmann::json::value_t::array: {
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::array to list");
                pybind11::list l(src.size());
                for (std::size_t i = 0; i < src.size(); ++i) {
                    l[i] = pybind11::cast(src[i]);
                }
                return l.release();
            }
            case nlohmann::json::value_t::object: {
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::object to dict");
                pybind11::dict d;
                for (auto& el : src.items()) {
                    d[pybind11::str(el.key())] = pybind11::cast(el.value());
                }
                return d.release();
            }
            case nlohmann::json::value_t::binary: {
                PYBIND11_JSON_PRINT_DEBUG("Casting json::value_t::binary to bytes");
                const auto& bin = src.get_binary();
                return pybind11::bytes(reinterpret_cast<const char*>(bin.data()), bin.size()).release();
            }
            default:
                PYBIND11_JSON_PRINT_DEBUG("Unable to cast json value type " << src.type_name());
                throw std::runtime_error("Unhandled json type");
        }
    }
};

} // namespace detail
} // namespace pybind11

#undef PYBIND11_JSON_PRINT_DEBUG 