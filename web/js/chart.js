(function() {
  function initDragZoom(svg, xScale, xAxis, focusLine, id) {
    var brush = d3.brushX()
      .extent([[0, 0], [svg.attr('width'), svg.attr('height')]])
      .on('end', brushended);
    var gBrush = svg.append('g').attr('class', 'brush').call(brush);
    function brushended(event) {
      if (!event.selection) return;
      var extent = event.selection.map(xScale.invert);
      svg.call(brush.move, null);
      if (extent[1] - extent[0] < 1000) return;
      xScale.domain(extent);
      svg.select('.x-axis').call(d3.axisBottom(xScale));
      svg.select('.focus-line').attr('d', typeof focusLine === 'function' ? focusLine : function(d) { return d3.line()(d); });
    }
  }
  window.initDragZoom = initDragZoom;
})();
