#pragma once

#include <cstddef>
#include <vector>

namespace banjo::modal {

// Row-major dense matrix. Mode matrices keep one mode per column, so a row is
// one degree of freedom's amplitude across every mode and a field evaluation
// walks contiguous memory.
struct DenseMatrix {
    std::size_t rows{};
    std::size_t cols{};
    std::vector<double> data;

    DenseMatrix() = default;
    DenseMatrix(std::size_t row_count, std::size_t column_count)
        : rows(row_count), cols(column_count), data(row_count * column_count, 0.0) {}

    [[nodiscard]] double &operator()(std::size_t row, std::size_t column) {
        return data[row * cols + column];
    }
    [[nodiscard]] double operator()(std::size_t row, std::size_t column) const {
        return data[row * cols + column];
    }
    [[nodiscard]] double *row(std::size_t index) { return data.data() + index * cols; }
    [[nodiscard]] const double *row(std::size_t index) const { return data.data() + index * cols; }
};

} // namespace banjo::modal
